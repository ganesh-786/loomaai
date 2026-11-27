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
    ({"TRANSCRIPTS_ALLOW_UNREVIEWED": "maybe"}, "TRANSCRIPTS_ALLOW_UNREVIEWED"),
])
def test_invalid_settings_name_the_variable_to_fix(env, needle):
    with pytest.raises(ConfigError, match=needle):
        Settings.from_env(env)


def test_public_view_hides_mongo_credentials():
    s = Settings.from_env({"MONGO_URI": "mongodb://user:secret@db:27017"})
    assert "secret" not in str(s.public_view())


def test_transcripts_default_to_the_data_folder_and_reviewed_pages_only():
    assert Settings.from_env({}).transcripts_dir == Path("/data/transcripts")
    assert Settings.from_env({"PIPELINE_DATA_DIR": "/x"}).transcripts_dir == Path("/x/transcripts")
    assert Settings.from_env({}).transcripts_allow_unreviewed is False


def test_transcript_settings_can_be_overridden_and_are_shown():
    s = Settings.from_env({"TRANSCRIPTS_DIR": "/t", "TRANSCRIPTS_ALLOW_UNREVIEWED": "1"})
    assert s.transcripts_dir == Path("/t") and s.transcripts_allow_unreviewed is True
    assert s.public_view()["transcripts"] == "/t (unreviewed allowed)"
