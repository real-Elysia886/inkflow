"""WorldState - Rich memory system for novel writing.

Truth files (inspired by inkos):
1. current_state    → WorldState core (characters, relationships, locations, timeline)
2. resource_ledger  → ResourceLedger (items, money, resources with quantities)
3. pending_hooks    → foreshadowing_pool + plot_threads
4. chapter_summaries → chapter_metas
5. subplot_board    → SubplotBoard (subplot progress tracking)
6. emotional_arcs   → EmotionalArcs (character emotional state tracking)
7. character_matrix → CharacterMatrix (interaction + information boundary tracking)
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator

from inkflow.memory.outline_window import OutlineWindow
from inkflow.memory.narrative_profile import NarrativeStrategyProfile


class Character(BaseModel):
    """A character with rich metadata."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    traits: str = ""
    age: str = ""
    gender: str = ""
    first_appearance: int = 0
    status: str = "alive"  # alive, dead, missing, unknown
    notes: str = ""
    tags: List[str] = Field(default_factory=list)
    custom_settings: Dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        return cls.model_validate(data)


class Relationship(BaseModel):
    """Relationship between two characters."""
    model_config = ConfigDict(populate_by_name=True)

    char1: str
    char2: str
    relation_type: str  # 师徒/朋友/敌对/恋人/同门/父子...
    description: str = ""
    chapter_started: int = 0
    status: str = "active"  # active, dissolved, evolved

    @property
    def key(self) -> str:
        return f"{self.char1}|{self.char2}"

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "Relationship":
        return cls.model_validate(data)


class TimelineEvent(BaseModel):
    """An event on the story timeline."""
    model_config = ConfigDict(populate_by_name=True)

    chapter: int
    time_desc: str  # "三天后" / "次日清晨" / "一个月后"
    event: str
    location: str = ""
    characters: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineEvent":
        return cls.model_validate(data)


class Location(BaseModel):
    """A location/setting in the story."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    location_type: str = ""  # 宗门/城市/秘境/荒野...
    first_appearance: int = 0
    known_characters: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "Location":
        return cls.model_validate(data)


class PlotThread(BaseModel):
    """An active plot thread (broader than foreshadowing)."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    thread_type: str = "subplot"  # main / subplot / romance / rivalry
    started_chapter: int = 0
    last_mentioned: int = 0
    status: str = "active"  # active, resolved, abandoned
    resolution: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "PlotThread":
        return cls.model_validate(data)


class ChapterMeta(BaseModel):
    """Rich metadata for a single chapter."""
    model_config = ConfigDict(populate_by_name=True)

    chapter_number: int
    summary: str = ""
    title: str = ""
    pov: str = ""  # 主视角角色
    location: str = ""
    mood: str = ""  # 紧张/温馨/悲伤/热血/搞笑...
    word_count: int = 0
    key_events: List[str] = Field(default_factory=list)
    characters_present: List[str] = Field(default_factory=list)
    foreshadowing_planted: List[str] = Field(default_factory=list)
    foreshadowing_resolved: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ChapterMeta":
        return cls.model_validate(data)


class ForeshadowingEntry(BaseModel):
    """A single foreshadowing element (伏笔)."""
    model_config = ConfigDict(populate_by_name=True)

    detail: str
    planted_chapter: int = 0
    status: str = "pending"  # pending / resolved / invalid

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ForeshadowingEntry":
        return cls.model_validate(data)


class StyleFingerprint(BaseModel):
    """Distilled writing style metrics."""
    model_config = ConfigDict(populate_by_name=True)

    tone: str = ""
    rhythm: str = ""
    dialogue_style: str = ""
    description_style: str = ""
    sentence_patterns: str = ""
    rhetoric: str = ""
    key_phrases: List[str] = Field(default_factory=list)
    avg_sentence_length: int = 0
    dialogue_ratio: float = 0.0  # 对话占比

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "StyleFingerprint":
        return cls.model_validate(data)


class ResourceEntry(BaseModel):
    """A single resource/item tracked in the ledger."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    owner: str = ""
    quantity: int = 1
    description: str = ""
    chapter_acquired: int = 0
    chapter_lost: int = 0  # 0 = still held
    status: str = "active"  # active, lost, consumed, destroyed

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceEntry":
        return cls.model_validate(data)


class ResourceLedger(BaseModel):
    """Tracks items, money, resources with quantities and lifecycle."""
    model_config = ConfigDict(populate_by_name=True)

    entries: Dict[str, ResourceEntry] = Field(default_factory=dict)  # key: "owner|name"

    def add(self, name: str, owner: str = "", quantity: int = 1,
            description: str = "", chapter: int = 0):
        key = f"{owner}|{name}"
        if key in self.entries and self.entries[key].status == "active":
            self.entries[key].quantity += quantity
        else:
            self.entries[key] = ResourceEntry(
                name=name, owner=owner, quantity=quantity,
                description=description, chapter_acquired=chapter,
            )

    def remove(self, name: str, owner: str = "", chapter: int = 0,
               reason: str = "lost"):
        key = f"{owner}|{name}"
        if key in self.entries:
            entry = self.entries[key]
            # Create updated version since BaseModel is used
            self.entries[key] = entry.model_copy(update={"status": reason, "chapter_lost": chapter})

    def get_active(self, owner: str = None) -> List[ResourceEntry]:
        results = [e for e in self.entries.values() if e.status == "active"]
        if owner is not None:
            results = [e for e in results if e.owner == owner]
        return results

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.entries.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceLedger":
        return cls(entries={k: ResourceEntry.from_dict(v) for k, v in data.items()})


class SubplotEntry(BaseModel):
    """A single subplot line."""
    model_config = ConfigDict(populate_by_name=True)

    name: str
    subplot_type: str = "subplot"  # main, subplot, romance, rivalry, mystery
    status: str = "active"  # active, stalled, resolved, abandoned
    started_chapter: int = 0
    last_advanced: int = 0  # last chapter where this subplot progressed
    summary: str = ""
    key_events: List[str] = Field(default_factory=list)
    characters_involved: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "SubplotEntry":
        return cls.model_validate(data)


class SubplotBoard(BaseModel):
    """Tracks subplot progress with stall detection."""
    model_config = ConfigDict(populate_by_name=True)

    subplots: List[SubplotEntry] = Field(default_factory=list)

    def add(self, name: str, subplot_type: str = "subplot",
            chapter: int = 0, characters: list = None):
        entry = SubplotEntry(name=name, subplot_type=subplot_type)
        entry.started_chapter = chapter
        entry.last_advanced = chapter
        entry.characters_involved = characters or []
        self.subplots.append(entry)

    def advance(self, name: str, chapter: int, event: str = ""):
        for i, s in enumerate(self.subplots):
            if s.name == name and s.status == "active":
                # Create updated copy
                updated_events = s.key_events.copy()
                if event:
                    updated_events.append(event)
                self.subplots[i] = s.model_copy(update={"last_advanced": chapter, "key_events": updated_events})
                return

    def get_stalled(self, stall_threshold: int = 5,
                    current_chapter: int = 0) -> List[SubplotEntry]:
        """Get subplots that haven't progressed in stall_threshold chapters."""
        return [
            s for s in self.subplots
            if s.status == "active"
            and current_chapter - s.last_advanced > stall_threshold
        ]

    def get_active(self) -> List[SubplotEntry]:
        return [s for s in self.subplots if s.status == "active"]

    def to_dict(self) -> dict:
        return {"subplots": [s.to_dict() for s in self.subplots]}

    @classmethod
    def from_dict(cls, data) -> "SubplotBoard":
        if isinstance(data, list):
            return cls(subplots=[SubplotEntry.from_dict(d) for d in data])
        if isinstance(data, dict):
            return cls(subplots=[SubplotEntry.from_dict(d) for d in data.get("subplots", [])])
        return cls()


class EmotionalState(BaseModel):
    """A single emotional state entry for a character."""
    model_config = ConfigDict(populate_by_name=True)

    chapter: int
    emotion: str  # 愤怒/悲伤/喜悦/恐惧/惊讶/厌恶/信任/期待
    intensity: int = 5  # 1-10
    trigger: str = ""  # what caused this emotion
    target: str = ""  # directed at whom/what

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionalState":
        return cls.model_validate(data)


class EmotionalArc(BaseModel):
    """Emotional arc for a single character."""
    model_config = ConfigDict(populate_by_name=True)

    character: str
    states: List[EmotionalState] = Field(default_factory=list)
    growth_arc: str = ""  # overall growth description

    def add_state(self, chapter: int, emotion: str, intensity: int = 5,
                  trigger: str = "", target: str = ""):
        self.states.append(EmotionalState(
            chapter=chapter, emotion=emotion, intensity=intensity,
            trigger=trigger, target=target,
        ))

    def get_recent(self, n: int = 3) -> List[EmotionalState]:
        return self.states[-n:]

    def get_dominant_emotion(self) -> str:
        """Get the most frequent emotion."""
        if not self.states:
            return ""
        counts: Dict[str, int] = {}
        for s in self.states:
            counts[s.emotion] = counts.get(s.emotion, 0) + 1
        return max(counts, key=counts.get)

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionalArc":
        return cls.model_validate(data)


class EmotionalArcs(BaseModel):
    """Tracks emotional arcs for all characters."""
    model_config = ConfigDict(populate_by_name=True)

    arcs: Dict[str, EmotionalArc] = Field(default_factory=dict)  # character_name → arc

    def add_state(self, character: str, chapter: int, emotion: str,
                  intensity: int = 5, trigger: str = "", target: str = ""):
        if character not in self.arcs:
            self.arcs[character] = EmotionalArc(character=character)
        self.arcs[character].add_state(chapter, emotion, intensity, trigger, target)

    def get_arc(self, character: str) -> Optional[EmotionalArc]:
        return self.arcs.get(character)

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self.arcs.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "EmotionalArcs":
        return cls(arcs={k: EmotionalArc.from_dict(v) for k, v in data.items()})


class InteractionRecord(BaseModel):
    """A record of two characters meeting/interacting."""
    model_config = ConfigDict(populate_by_name=True)

    char1: str
    char2: str
    chapter: int
    interaction_type: str = "meeting"  # meeting, conversation, fight, cooperation
    location: str = ""
    summary: str = ""

    @property
    def key(self) -> str:
        return f"{min(self.char1, self.char2)}|{max(self.char1, self.char2)}|{self.chapter}"

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "InteractionRecord":
        return cls.model_validate(data)


class InfoBoundary(BaseModel):
    """Tracks what information a character knows."""
    model_config = ConfigDict(populate_by_name=True)

    character: str
    known_facts: List[str] = Field(default_factory=list)  # facts this character knows
    known_in_chapter: Dict[str, int] = Field(default_factory=dict)  # fact → chapter learned

    def learn(self, fact: str, chapter: int):
        if fact not in self.known_facts:
            self.known_facts.append(fact)
            self.known_in_chapter[fact] = chapter

    def knows(self, fact: str) -> bool:
        return fact in self.known_facts

    def to_dict(self) -> dict:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict) -> "InfoBoundary":
        return cls.model_validate(data)


class CharacterMatrix(BaseModel):
    """Tracks character interactions and information boundaries."""
    model_config = ConfigDict(populate_by_name=True)

    interactions: List[InteractionRecord] = Field(default_factory=list)
    info_boundaries: Dict[str, InfoBoundary] = Field(default_factory=dict)  # character → boundary

    def add_interaction(self, char1: str, char2: str, chapter: int,
                        interaction_type: str = "meeting", location: str = "",
                        summary: str = ""):
        record = InteractionRecord(char1=char1, char2=char2, chapter=chapter, 
                                   interaction_type=interaction_type, location=location, summary=summary)
        self.interactions.append(record)

    def add_knowledge(self, character: str, fact: str, chapter: int):
        if character not in self.info_boundaries:
            self.info_boundaries[character] = InfoBoundary(character=character)
        self.info_boundaries[character].learn(fact, chapter)

    def get_interactions_between(self, char1: str, char2: str) -> List[InteractionRecord]:
        return [
            r for r in self.interactions
            if {r.char1, r.char2} == {char1, char2}
        ]

    def get_recent_interactions(self, character: str, n: int = 5) -> List[InteractionRecord]:
        char_interactions = [
            r for r in self.interactions
            if r.char1 == character or r.char2 == character
        ]
        return char_interactions[-n:]

    def does_character_know(self, character: str, fact: str) -> bool:
        if character not in self.info_boundaries:
            return False
        return self.info_boundaries[character].knows(fact)

    def to_dict(self) -> dict:
        return {
            "interactions": [r.to_dict() for r in self.interactions],
            "info_boundaries": {k: v.to_dict() for k, v in self.info_boundaries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CharacterMatrix":
        return cls(
            interactions=[InteractionRecord.from_dict(d) for d in data.get("interactions", [])],
            info_boundaries={k: InfoBoundary.from_dict(v) for k, v in data.get("info_boundaries", {}).items()}
        )


class WorldState(BaseModel):
    """Complete story memory system.

    This is the single source of truth for everything the AI needs
    to maintain consistency across chapters.
    """
    model_config = ConfigDict(populate_by_name=True)

    # Basic
    world_setting: str = ""
    current_chapter: int = 0
    setting_templates: Dict[str, str] = Field(default_factory=dict)

    # Characters
    characters: Dict[str, Character] = Field(default_factory=dict)
    relationships: Dict[str, Relationship] = Field(default_factory=dict)  # key: "char1|char2"

    # World
    locations: Dict[str, Location] = Field(default_factory=dict)
    timeline: List[TimelineEvent] = Field(default_factory=list)

    # Plot
    chapter_metas: Dict[int, ChapterMeta] = Field(default_factory=dict)
    plot_threads: List[PlotThread] = Field(default_factory=list)
    foreshadowing_pool: List[ForeshadowingEntry] = Field(default_factory=list)
    used_tropes: List[str] = Field(default_factory=list)

    # Truth files (inkos-inspired)
    resource_ledger: ResourceLedger = Field(default_factory=ResourceLedger)
    subplot_board: SubplotBoard = Field(default_factory=SubplotBoard)
    emotional_arcs: EmotionalArcs = Field(default_factory=EmotionalArcs)
    character_matrix: CharacterMatrix = Field(default_factory=CharacterMatrix)

    # Input governance
    author_intent: str = ""   # long-term author intent
    current_focus: str = ""   # current 1-3 chapter focus

    # Style
    style_fingerprint: StyleFingerprint = Field(default_factory=StyleFingerprint)

    # Legacy compatibility
    chapter_summaries: Dict[int, str] = Field(default_factory=dict)
    plot_arc: List[str] = Field(default_factory=list)

    # Outline window (rolling 5-chapter outline)
    outline_window: OutlineWindow = Field(default_factory=OutlineWindow)

    # Narrative strategy profile (distilled from reference book)
    narrative_profile: Optional[NarrativeStrategyProfile] = None

    @model_validator(mode='before')
    @classmethod
    def upgrade_schema(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # v1 → v2: foreshadowing_pool items may lack "planted_chapter"
            if data.get("schema_version", 1) < 2:
                for f in data.get("foreshadowing_pool", []):
                    if isinstance(f, dict):
                        f.setdefault("planted_chapter", 0)
                        f.setdefault("status", "pending")
            # Legacy format: subplot_board saved as bare list instead of {"subplots": [...]}
            if isinstance(data.get("subplot_board"), list):
                data["subplot_board"] = {"subplots": data["subplot_board"]}

            # v3 → v4: chapter_metas from List to Dict (keyed by chapter_number)
            if isinstance(data.get("chapter_metas"), list):
                metas_list = data["chapter_metas"]
                metas_dict = {}
                for i, cm in enumerate(metas_list):
                    if isinstance(cm, dict):
                        ch_num = cm.get("chapter_number", i + 1)
                        metas_dict[ch_num] = cm
                    elif hasattr(cm, "chapter_number"):
                        metas_dict[cm.chapter_number] = cm
                data["chapter_metas"] = metas_dict

            # v3 → v4: chapter_summaries from List to Dict (keyed by chapter_number)
            if isinstance(data.get("chapter_summaries"), list):
                summaries_list = data["chapter_summaries"]
                summaries_dict = {}
                for i, s in enumerate(summaries_list):
                    if s:  # skip empty strings
                        summaries_dict[i + 1] = s
                data["chapter_summaries"] = summaries_dict
        return data

    # ── Character operations ──

    def add_character(self, name: str, description: str = "", traits: str = "",
                      age: str = "", gender: str = ""):
        ch = Character(name=name, description=description, traits=traits,
                       age=age, gender=gender, first_appearance=self.current_chapter)
        self.characters[name] = ch

    def get_character(self, name: str) -> Optional[Character]:
        return self.characters.get(name)

    def get_alive_characters(self) -> List[Character]:
        return [c for c in self.characters.values() if c.status == "alive"]

    # ── Relationship operations ──

    def add_relationship(self, char1: str, char2: str, relation_type: str,
                         description: str = ""):
        r = Relationship(char1=char1, char2=char2, relation_type=relation_type,
                         description=description, chapter_started=self.current_chapter)
        self.relationships[r.key] = r

    def get_relationships(self, char_name: str) -> List[Relationship]:
        return [r for r in self.relationships.values()
                if (r.char1 == char_name or r.char2 == char_name) and r.status == "active"]

    # ── Location operations ──

    def add_location(self, name: str, description: str = "", location_type: str = ""):
        loc = Location(name=name, description=description, location_type=location_type)
        loc.first_appearance = self.current_chapter
        self.locations[name] = loc

    # ── Timeline operations ──

    def add_timeline_event(self, time_desc: str, event: str,
                           location: str = "", characters: list = None):
        te = TimelineEvent(
            chapter=self.current_chapter, time_desc=time_desc,
            event=event, location=location, characters=characters or [],
        )
        self.timeline.append(te)

    # ── Chapter operations ──

    def add_chapter_meta(self, chapter_number: int, summary: str = "",
                         title: str = "", pov: str = "", location: str = "",
                         mood: str = "", word_count: int = 0,
                         key_events: list = None, characters_present: list = None):
        cm = ChapterMeta(chapter_number=chapter_number, summary=summary)
        cm.title = title
        cm.pov = pov
        cm.location = location
        cm.mood = mood
        cm.word_count = word_count
        cm.key_events = key_events or []
        cm.characters_present = characters_present or []

        self.chapter_metas[chapter_number] = cm
        self.chapter_summaries[chapter_number] = summary
        self.current_chapter = max(self.current_chapter, chapter_number)

    def add_chapter_summary(self, chapter_number: int, summary: str):
        """Legacy wrapper for add_chapter_meta."""
        self.add_chapter_meta(chapter_number=chapter_number, summary=summary)

    def remove_chapter_meta(self, chapter_number: int):
        """删除章节元数据"""
        self.chapter_metas.pop(chapter_number, None)
        self.chapter_summaries.pop(chapter_number, None)

        if self.chapter_metas:
            self.current_chapter = max(self.chapter_metas.keys())
        else:
            self.current_chapter = 0

    # ── Plot operations ──

    def add_plot_thread(self, name: str, description: str = "",
                        thread_type: str = "subplot"):
        t = PlotThread(name=name, description=description, thread_type=thread_type)
        t.started_chapter = self.current_chapter
        t.last_mentioned = self.current_chapter
        self.plot_threads.append(t)

    def add_foreshadowing(self, detail: str, related_chapter: int = None):
        self.foreshadowing_pool.append(ForeshadowingEntry(
            detail=detail,
            planted_chapter=related_chapter if related_chapter is not None else self.current_chapter,
            status="pending",
        ))

    def add_used_trope(self, trope: str):
        if trope not in self.used_tropes:
            self.used_tropes.append(trope)

    # ── Query operations ──

    def get_recent_summaries(self, n: int = 5) -> List[str]:
        if not self.chapter_summaries:
            return []
        sorted_keys = sorted(self.chapter_summaries.keys())
        return [self.chapter_summaries[k] for k in sorted_keys[-n:]]

    def get_recent_metas(self, n: int = 5) -> List[ChapterMeta]:
        if not self.chapter_metas:
            return []
        sorted_keys = sorted(self.chapter_metas.keys())
        return [self.chapter_metas[k] for k in sorted_keys[-n:]]

    def get_active_plot_threads(self) -> List[PlotThread]:
        return [t for t in self.plot_threads if t.status == "active"]

    def get_pending_foreshadowing(self) -> List[ForeshadowingEntry]:
        return [f for f in self.foreshadowing_pool if f.status == "pending"]

    def get_stale_foreshadowing(self, max_age: int = 10) -> List[ForeshadowingEntry]:
        """Foreshadowing planted more than max_age chapters ago and still pending."""
        return [f for f in self.foreshadowing_pool
                if f.status == "pending"
                and self.current_chapter - f.planted_chapter > max_age]

    def get_character_appearances(self, n: int = 5) -> Dict[str, int]:
        """Count character appearances in recent n chapters."""
        recent = self.get_recent_metas(n)
        counts: Dict[str, int] = {}
        for cm in recent:
            for ch in cm.characters_present:
                counts[ch] = counts.get(ch, 0) + 1
        return counts

    def get_mood_sequence(self, n: int = 5) -> List[str]:
        """Get mood of recent n chapters for rhythm analysis."""
        return [cm.mood for cm in self.get_recent_metas(n) if cm.mood]

    # ── Serialization ──

    def to_dict(self) -> dict:
        d = self.model_dump()
        d["schema_version"] = 4
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "WorldState":
        return cls.model_validate(data)

    def save(self, file_path: str):
        from inkflow.utils.atomic_io import write_json_atomic
        write_json_atomic(file_path, self.to_dict())

    def load(self, file_path: str):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        obj = self.from_dict(data)
        self.__dict__.update(obj.__dict__)

    def __repr__(self):
        return (f"<WorldState: ch{self.current_chapter}, "
                f"{len(self.characters)} chars, "
                f"{len(self.relationships)} rels, "
                f"{len(self.locations)} locs, "
                f"{len(self.chapter_metas)} chapters>")
