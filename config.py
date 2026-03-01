OLLAMA_MODEL = "devstral-small-2:24b-cloud"
OLLAMA_BASE_URL = "http://localhost:11434"
SHORT_TERM_WINDOW = 20
HISTORY_BACKEND = "json"
HISTORY_DIR = ".agent_history"
MAX_ITERATIONS = 10

# Sanity-clamp at runtime so a misconfigured value never causes unbound-variable crashes.
assert isinstance(MAX_ITERATIONS, int) and MAX_ITERATIONS > 0, \
    "MAX_ITERATIONS must be a positive integer"
assert isinstance(SHORT_TERM_WINDOW, int) and SHORT_TERM_WINDOW > 0, \
    "SHORT_TERM_WINDOW must be a positive integer"