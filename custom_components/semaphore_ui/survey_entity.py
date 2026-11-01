"""Input entities (text / number / select) for the survey variables of a template.

The value of such an entity is what the *Start* and *Dry run* buttons send to
Semaphore. Secret variables get no entity on purpose (a value in the state
machine would be stored in the database) - use the action for them.
"""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import SemaphoreConfigEntry, SemaphoreCoordinator
from .entity import SemaphoreTemplateEntity
from .survey import SurveyVar


def survey_unique_id(entry_id: str, template_id: int, name: str) -> str:
    """Unique id of the input entity of a survey variable."""
    return f"{entry_id}_{template_id}_survey_{name}"


class SemaphoreSurveyEntity(SemaphoreTemplateEntity, RestoreEntity):
    """Common part of the input entities."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: SemaphoreCoordinator, template_id: int, var: SurveyVar
    ) -> None:
        super().__init__(coordinator, template_id, f"survey_{var.name}")
        self.var_name = var.name
        self._attr_name = var.title
        names = [item.name for item in coordinator.survey_vars(template_id)]
        self._attr_extra_state_attributes = {
            "variable": var.name,
            # position in the template, so a card can show the fields in this order
            "order": names.index(var.name) if var.name in names else 0,
            "required": var.required,
            "description": var.description or None,
        }

    @property
    def var(self) -> SurveyVar | None:
        """Current definition (``None`` if it was removed in Semaphore)."""
        for var in self.coordinator.survey_vars(self.template_id):
            if var.name == self.var_name:
                return var
        return None

    @property
    def available(self) -> bool:
        """Available while the variable exists."""
        return super().available and self.var is not None

    def _remember(self, value: object) -> None:
        """Tell the coordinator which value the buttons shall send."""
        self.coordinator.set_survey_value(self.template_id, self.var_name, value)

    async def async_added_to_hass(self) -> None:
        """Restore the last value, otherwise start with the default."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._restore(last.state)
        else:
            self._apply_default()

    async def async_will_remove_from_hass(self) -> None:
        """Forget the value."""
        self._remember(None)
        await super().async_will_remove_from_hass()

    def _restore(self, state: str) -> None:
        raise NotImplementedError

    def _apply_default(self) -> None:
        raise NotImplementedError


@callback
def async_setup_survey_platform(
    hass: HomeAssistant,
    entry: SemaphoreConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    *,
    domain: str,
    wants: Callable[[SurveyVar], bool],
    factory: Callable[[SemaphoreCoordinator, int, SurveyVar], Entity],
) -> None:
    """Create the input entities of one platform and keep them in sync.

    New survey variables get an entity, removed ones lose it again.
    """
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    known: set[str] = set()

    def _sync() -> None:
        wanted: dict[str, tuple[int, SurveyVar]] = {}
        for template_id in coordinator.data.templates:
            for var in coordinator.survey_vars(template_id):
                if wants(var):
                    unique_id = survey_unique_id(entry.entry_id, template_id, var.name)
                    wanted[unique_id] = (template_id, var)

        new = [uid for uid in wanted if uid not in known]
        if new:
            known.update(new)
            async_add_entities([factory(coordinator, *wanted[uid]) for uid in new])

        # Entities of variables that no longer exist (also from earlier runs).
        prefix = f"{entry.entry_id}_"
        for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
            unique_id = reg_entry.unique_id
            if (
                reg_entry.domain == domain
                and reg_entry.platform == DOMAIN
                and unique_id.startswith(prefix)
                and "_survey_" in unique_id
                and unique_id not in wanted
                # a template that vanished takes its devices with it
                and any(
                    unique_id.startswith(f"{prefix}{tid}_survey_")
                    for tid in coordinator.data.templates
                )
            ):
                registry.async_remove(reg_entry.entity_id)
                known.discard(unique_id)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))
