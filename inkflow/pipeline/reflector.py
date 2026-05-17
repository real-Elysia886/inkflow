"""Reflector - Applies Observer output to WorldState via structured updates.

Instead of letting LLM directly modify truth files (which can cause drift),
Reflector uses code-level validation and immutable updates.
"""

from typing import Dict, Any

from inkflow.memory.world_state import WorldState


class Reflector:
    """Applies Observer-extracted facts to WorldState with validation."""

    def apply(self, world_state: WorldState, observations: Dict[str, Any],
              chapter_number: int) -> WorldState:
        """Apply observations to world state immutably.

        Args:
            world_state: Current WorldState (will be mutated).
            observations: Observer output with 9 keys.
            chapter_number: Current chapter number.

        Returns:
            The updated WorldState.
        """
        self._apply_characters(world_state, observations.get("characters") or {})
        self._apply_locations(world_state, observations.get("locations") or {})
        self._apply_resources(world_state, observations.get("resources") or {}, chapter_number)
        self._apply_relationships(world_state, observations.get("relationships") or {})
        self._apply_emotions(world_state, observations.get("emotions") or [], chapter_number)
        self._apply_information(world_state, observations.get("information") or {}, chapter_number)
        self._apply_foreshadowing(world_state, observations.get("foreshadowing") or {})
        self._apply_timeline(world_state, observations.get("time") or {}, chapter_number)
        self._apply_physical_state(world_state, observations.get("physical_state") or [])
        return world_state

    def _apply_characters(self, ws: WorldState, data: dict):
        """Update character appearances and status changes."""
        for ch_data in data.get("status_changes") or []:
            name = ch_data.get("name", "")
            if name in ws.characters:
                new_status = ch_data.get("new_status", "")
                if new_status and new_status in ("alive", "dead", "missing", "unknown"):
                    ws.characters[name].status = new_status

    def _apply_locations(self, ws: WorldState, data: dict):
        """Register new locations."""
        for loc_data in data.get("new") or []:
            name = loc_data.get("name", "")
            if name and name not in ws.locations:
                ws.add_location(
                    name=name,
                    description=loc_data.get("description", ""),
                    location_type=loc_data.get("type", ""),
                )

    def _apply_resources(self, ws: WorldState, data: dict, chapter: int):
        """Update resource ledger."""
        for item in data.get("acquired") or []:
            ws.resource_ledger.add(
                name=item.get("name", ""),
                owner=item.get("owner", ""),
                quantity=item.get("quantity", 1),
                description=item.get("description", ""),
                chapter=chapter,
            )
        for item in data.get("lost") or []:
            ws.resource_ledger.remove(
                name=item.get("name", ""),
                owner=item.get("owner", ""),
                chapter=chapter,
                reason="lost",
            )
        for item in data.get("consumed") or []:
            ws.resource_ledger.remove(
                name=item.get("name", ""),
                owner=item.get("owner", ""),
                chapter=chapter,
                reason="consumed",
            )

    def _apply_relationships(self, ws: WorldState, data: dict):
        """Register new or changed relationships."""
        for rel in data.get("new") or []:
            char1 = rel.get("char1", "")
            char2 = rel.get("char2", "")
            rel_type = rel.get("type", "")
            if char1 and char2 and rel_type:
                key = f"{char1}|{char2}"
                if key not in ws.relationships:
                    ws.add_relationship(char1, char2, rel_type, rel.get("description", ""))

        for rel in data.get("changed") or []:
            char1 = rel.get("char1", "")
            char2 = rel.get("char2", "")
            key = f"{char1}|{char2}"
            if key in ws.relationships:
                new_type = rel.get("new_type", "")
                if new_type:
                    ws.relationships[key].relation_type = new_type

    def _apply_emotions(self, ws: WorldState, data: list, chapter: int):
        """Record emotional states."""
        for emo in data:
            char = emo.get("character", "")
            emotion = emo.get("emotion", "")
            if char and emotion:
                ws.emotional_arcs.add_state(
                    character=char,
                    chapter=chapter,
                    emotion=emotion,
                    intensity=emo.get("intensity", 5),
                    trigger=emo.get("trigger", ""),
                    target=emo.get("target", ""),
                )

    def _apply_information(self, ws: WorldState, data: dict, chapter: int):
        """Update information boundaries."""
        for item in data.get("learned") or []:
            char = item.get("character", "")
            fact = item.get("fact", "")
            if char and fact:
                ws.character_matrix.add_knowledge(char, fact, chapter)

    def _apply_foreshadowing(self, ws: WorldState, data: dict):
        """Update foreshadowing pool."""
        for fs_text in data.get("planted") or []:
            if fs_text:
                ws.add_foreshadowing(fs_text)

        for fs_text in data.get("resolved") or []:
            if not fs_text:
                continue
            for fs in ws.foreshadowing_pool:
                if fs.status == "pending" and fs_text in fs.detail:
                    fs.status = "resolved"

    def _apply_timeline(self, ws: WorldState, data: dict, chapter: int):
        """Add timeline event."""
        time_desc = data.get("time_desc", "")
        if time_desc:
            ws.add_timeline_event(
                time_desc=time_desc,
                event=f"第{chapter}章事件",
            )

    def _apply_physical_state(self, ws: WorldState, data: list):
        """Record physical state changes as character notes."""
        for ps in data:
            char = ps.get("character", "")
            changes = ps.get("changes", "")
            if char and changes and char in ws.characters:
                existing = ws.characters[char].notes
                new_note = f"[ch{ws.current_chapter}] {changes}"
                ws.characters[char].notes = f"{existing}\n{new_note}".strip()
