"""
constants.py — project-wide constants.

NOISE_LABELS is a frozenset of lowercase label strings that are filtered out
of inference results before they reach the detection pipeline.  It covers:

  - Generic BirdNET catch-all labels ("background", "noise", etc.)
  - All 198 FSD50K non-bird sound classes from the Perch v2
    inat2024_fsd50k label namespace (stored lowercase for O(1) lookup).

Both inference backends (inference_birdnet.py, inference_perch.py) import this
set and check ``label.lower() not in NOISE_LABELS``.  The BOU filter provides
an independent second line of defence, but listing non-bird classes here means
they are dropped inside run_inference() before they ever reach the detect loop.
"""

NOISE_LABELS: frozenset[str] = frozenset({
    # ── Generic BirdNET catch-all labels ─────────────────────────────────────
    "background", "noise", "silence", "other",

    # ── Perch v2 FSD50K non-bird sound classes (198 entries) ─────────────────
    "accelerating_and_revving_and_vroom", "accordion", "acoustic_guitar",
    "aircraft", "alarm", "animal", "applause", "bark", "bass_drum",
    "bass_guitar", "bathtub_(filling_or_washing)", "bell", "bicycle",
    "bicycle_bell", "boat_and_water_vehicle", "boiling", "boom",
    "bowed_string_instrument", "brass_instrument", "breathing",
    "burping_and_eructation", "bus", "buzz", "camera", "car",
    "car_passing_by", "cat", "chatter", "cheering", "chewing_and_mastication",
    "chicken_and_rooster", "child_speech_and_kid_speaking", "chime",
    "chink_and_clink", "chirp_and_tweet", "chuckle_and_chortle",
    "church_bell", "clapping", "clock", "coin_(dropping)",
    "computer_keyboard", "conversation", "cough", "cowbell", "crack",
    "crackle", "crash_cymbal", "cricket", "crow", "crowd",
    "crumpling_and_crinkling", "crushing", "crying_and_sobbing",
    "cupboard_open_or_close", "cutlery_and_silverware", "cymbal",
    "dishes_and_pots_and_pans", "dog", "domestic_animals_and_pets",
    "domestic_sounds_and_home_sounds", "door", "doorbell",
    "drawer_open_or_close", "drill", "drip", "drum", "drum_kit",
    "electric_guitar", "engine", "engine_starting", "explosion", "fart",
    "female_singing", "female_speech_and_woman_speaking",
    "fill_(with_liquid)", "finger_snapping", "fire", "fireworks",
    "fixed-wing_aircraft_and_airplane", "fowl", "frog", "frying_(food)",
    "gasp", "giggle", "glass", "glockenspiel", "gong", "growling",
    "guitar", "gull_and_seagull", "gunshot_and_gunfire", "gurgling",
    "hammer", "hands", "harmonica", "harp", "hi-hat", "hiss",
    "human_group_actions", "human_voice", "idling", "insect",
    "keyboard_(musical)", "keys_jangling", "knock", "laughter", "liquid",
    "livestock_and_farm_animals_and_working_animals", "male_singing",
    "male_speech_and_man_speaking", "mallet_percussion",
    "marimba_and_xylophone", "mechanical_fan", "mechanisms", "meow",
    "microwave_oven", "motor_vehicle_(road)", "motorcycle", "music",
    "musical_instrument", "ocean", "organ", "packing_tape_and_duct_tape",
    "percussion", "piano", "plucked_string_instrument", "pour",
    "power_tool", "printer", "purr", "race_car_and_auto_racing",
    "rail_transport", "rain", "raindrop", "ratchet_and_pawl", "rattle",
    "rattle_(instrument)", "respiratory_sounds", "ringtone", "run",
    "sawing", "scissors", "scratching_(performance_technique)", "screaming",
    "screech", "shatter", "shout", "sigh", "singing",
    "sink_(filling_or_washing)", "siren", "skateboard", "slam",
    "sliding_door", "snare_drum", "sneeze", "speech", "speech_synthesizer",
    "splash_and_splatter", "squeak", "stream", "strum",
    "subway_and_metro_and_underground", "tabla", "tambourine", "tap",
    "tearing", "telephone", "thump_and_thud", "thunder", "thunderstorm",
    "tick", "tick-tock", "toilet_flush", "tools",
    "traffic_noise_and_roadway_noise", "train", "trickle_and_dribble",
    "truck", "trumpet", "typewriter", "typing", "vehicle",
    "vehicle_horn_and_car_horn_and_honking", "walk_and_footsteps", "water",
    "water_tap_and_faucet", "waves_and_surf", "whispering",
    "whoosh_and_swoosh_and_swish", "wild_animals", "wind", "wind_chime",
    "wind_instrument_and_woodwind_instrument", "wood", "writing", "yell",
    "zipper_(clothing)",

    # ── Legacy BirdNET labels (kept for compatibility) ────────────────────────
    "human non-vocal", "power tools",
})


# ── Human-sound label subset ──────────────────────────────────────────────────
#
# HUMAN_LABELS is a frozenset of lowercase label strings that specifically
# represent human voices and body sounds.  It is a deliberate subset of
# NOISE_LABELS, used by the privacy filter (filters/privacy_filter.py) to
# detect human presence in a saved clip and suppress it before persistence.
#
# Covers two namespaces:
#
#   BirdNET catch-all:
#     "human non-vocal" — the only explicit human label in BirdNET GLOBAL 6K.
#
#   Perch v2 FSD50K classes:
#     Scientific-name-style entries whose common name is the class itself
#     (e.g. self._classes[i] == "speech").  These map through sci_to_common
#     unchanged (not in BTO JSON) and are checked against this set.

HUMAN_LABELS: frozenset[str] = frozenset({
    # BirdNET
    "human non-vocal",

    # Perch FSD50K — voice and vocalisations
    "speech",
    "speech_synthesizer",
    "human_voice",
    "male_speech_and_man_speaking",
    "female_speech_and_woman_speaking",
    "child_speech_and_kid_speaking",
    "conversation",
    "whispering",
    "chatter",
    "cheering",

    # Perch FSD50K — crowd and group
    "crowd",
    "human_group_actions",

    # Perch FSD50K — emotional / reactive vocalisations
    "crying_and_sobbing",
    "laughter",
    "chuckle_and_chortle",
    "giggle",
    "screaming",
    "shout",
    "yell",
    "gasp",
    "sigh",

    # Perch FSD50K — respiratory
    "cough",
    "sneeze",
    "breathing",
    "respiratory_sounds",

    # Perch FSD50K — singing (human)
    "singing",
    "male_singing",
    "female_singing",
})
