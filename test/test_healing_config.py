from self_healing_whois.healing_config import load_env


def test_env_loading_and_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv('WHOIS_LLM_API_KEY', raising=False)
    monkeypatch.setenv('WHOIS_LLM_MODEL', 'existing-model')
    path = tmp_path / '.env'
    path.write_text('# comment\nWHOIS_LLM_API_KEY="test-only"\nWHOIS_LLM_MODEL=file-model\n', encoding='utf-8-sig')
    load_env(path)
    import os
    assert os.environ['WHOIS_LLM_API_KEY'] == 'test-only'
    assert os.environ['WHOIS_LLM_MODEL'] == 'existing-model'
    monkeypatch.delenv('WHOIS_LLM_API_KEY')
