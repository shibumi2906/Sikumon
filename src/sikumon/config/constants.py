"""Values shared throughout Sikumon."""

APP_NAME = "Sikumon"
APP_VERSION = "0.1.0"
APP_DATA_FOLDER = APP_NAME
DATABASE_FILENAME = "sikumon.db"
LOG_FOLDER = "logs"
MODELS_FOLDER = "models"
MEETINGS_FOLDER = "meetings"
CACHE_FOLDER = "cache"
LOG_FILENAME = "sikumon.log"

IVRIT_MODEL_ID = "ivrit-ai/whisper-large-v3-turbo-ct2"
IVRIT_MODEL_REVISION: str | None = "72ad623a37947395efcc3933132353790e5a12f5"
TRANSCRIPTION_LANGUAGE = "he"
TRANSCRIPTION_DEVICE = "cpu"
TRANSCRIPTION_COMPUTE_TYPE = "int8"

DEFAULT_ANALYSIS_PROVIDER = "openai"
DEFAULT_ANALYSIS_MODEL = "gpt-4.1-mini-2025-04-14"
ANALYSIS_PROMPT_VERSION = "1"
ANALYSIS_SCHEMA_VERSION = "1"
# Count each UTF-8 byte as a token. This deliberately overestimates normal Hebrew and
# leaves ample space inside the selected model's 1,047,576-token context window.
MAX_ANALYSIS_INPUT_ESTIMATED_TOKENS = 200_000
ANALYSIS_REQUEST_TIMEOUT_SECONDS = 60.0

CURRENT_SCHEMA_VERSION = 1
