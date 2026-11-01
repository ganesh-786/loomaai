from pathlib import Path

import pytest

from looma_pipeline.config import DEFAULT_EMBED_MODEL_REVISION, ConfigError, Settings


def test_defaults_work_inside_the_container():
    s = Settings.from_env({})
    assert s.mongo_uri == "mongodb://looma-db:27017"
    assert s.data_dir == Path("/data")
    assert s.embed_model_revision == DEFAULT_EMBED_MODEL_REVISION
    assert s.model_dir.name == DEFAULT_EMBED_MODEL_REVISION
    assert not s.is_cehrd_server


def test_env_overrides_and_cehrd_flag():
    s = Settings.from_env({"LOOMA_SERVER": "cehrd", "EMBED_THREADS": "2", "OCR_ENABLED": "0"})
    assert s.is_cehrd_server
    assert s.embed_threads == 2
    assert s.ocr_enabled is False


@pytest.mark.parametrize("env, needle", [
    ({"EMBED_THREADS": "two"}, "EMBED_THREADS"),
    ({"EMBED_THREADS": "0"}, "minimum"),
    ({"OCR_ENABLED": "maybe"}, "OCR_ENABLED"),
    ({"CHUNK_OVERLAP_TOKENS": "300"}, "CHUNK_OVERLAP_TOKENS"),
    ({"CHUNK_MAX_TOKENS": "600", "CHUNK_TARGET_TOKENS": "300"}, "CHUNK_MAX_TOKENS"),
    ({"MONGO_URI": "localhost:27017"}, "MONGO_URI"),
])
def test_invalid_settings_name_the_variable_to_fix(env, needle):
    with pytest.raises(ConfigError, match=needle):
        Settings.from_env(env)


def test_public_view_hides_mongo_credentials():
    s = Settings.from_env({"MONGO_URI": "mongodb://user:secret@db:27017"})
    assert "secret" not in str(s.public_view())
