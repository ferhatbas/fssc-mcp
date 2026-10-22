"""
.fs-workspace ve Ajan Markdown Versiyonlama Birim Testleri (unittest)
"""

import os
import shutil
import tempfile
import unittest
from server.fs_workspace import (
    ensure_fs_workspace,
    get_agent_markdown_info,
    save_agent_markdown,
    restore_agent_version,
    inherit_from_standard,
    promote_to_global,
    record_agent_learning,
    sync_project_to_workspace,
    load_project_from_workspace
)


class TestFsWorkspace(unittest.TestCase):
    def setUp(self):
        self.temp_project = tempfile.mkdtemp(prefix="fs_workspace_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_project, ignore_errors=True)

    def test_ensure_and_inherit(self):
        ws_dir = ensure_fs_workspace(self.temp_project)
        self.assertTrue(os.path.isdir(ws_dir))
        self.assertTrue(os.path.isdir(os.path.join(ws_dir, "agents")))
        self.assertTrue(os.path.isdir(os.path.join(ws_dir, "agents", "history")))

        info = get_agent_markdown_info(self.temp_project, "BACKEND_DEV", "BACKEND_DEV")
        self.assertEqual(info["agent_id"], "BACKEND_DEV")
        self.assertEqual(info["current_version"], "v1")
        self.assertEqual(len(info["versions"]), 1)
        self.assertTrue(
            "Developer" in info["active_content"] 
            or "Senior" in info["active_content"] 
            or "Prompt" in info["active_content"]
        )

    def test_version_save_and_restore(self):
        # v1 oluşsun
        info_v1 = get_agent_markdown_info(self.temp_project, "QA", "QA")
        self.assertEqual(info_v1["current_version"], "v1")

        # v2 kaydet
        v2_content = info_v1["active_content"] + "\n\n### Özel Kural: Tüm testler pytest ile çalışmalı."
        info_v2 = save_agent_markdown(
            project_path=self.temp_project,
            agent_id="QA",
            role="QA",
            content=v2_content,
            commit_message="Pytest kuralı eklendi",
            author="Ferhat"
        )
        self.assertEqual(info_v2["current_version"], "v2")
        self.assertEqual(len(info_v2["versions"]), 2)
        self.assertIn("Özel Kural", info_v2["active_content"])

        # v1'e geri dön (Rollback)
        info_restored = restore_agent_version(
            project_path=self.temp_project,
            agent_id="QA",
            role="QA",
            target_version_id="v1",
            author="Ferhat"
        )
        self.assertEqual(info_restored["current_version"], "v3")
        self.assertEqual(len(info_restored["versions"]), 3)
        self.assertNotIn("Özel Kural", info_restored["active_content"])

    def test_record_learning(self):
        info = get_agent_markdown_info(self.temp_project, "PM", "PM")
        self.assertEqual(info["current_version"], "v1")

        updated = record_agent_learning(
            project_path=self.temp_project,
            agent_id="PM",
            role="PM",
            learning_note="Müşteri görüşmelerinde acceptance criteria mutlaka netleştirilmeli.",
            task_title="PRD Analizi"
        )
        self.assertIsNotNone(updated)
        self.assertIn("acceptance criteria", updated["active_content"])
        self.assertEqual(updated["current_version"], "v2")

    def test_workspace_sync_and_load(self):
        data = {
            "id": "test_proj",
            "name": "Test Projesi",
            "jira_issues": {
                "JIRA-1": {"id": "JIRA-1", "title": "Test Görevi", "status": "BACKLOG"}
            },
            "tasks": {
                "T-1": {"id": "T-1", "title": "Kanban Görevi", "state": "BACKLOG"}
            },
            "uploaded_specs": [
                {"id": "SPEC-1", "title": "Şartname 1"}
            ]
        }

        sync_project_to_workspace(self.temp_project, data)

        loaded = load_project_from_workspace(self.temp_project)
        self.assertIsNotNone(loaded)
        self.assertIn("JIRA-1", loaded.get("jira_issues", {}))
        self.assertEqual(loaded["jira_issues"]["JIRA-1"]["title"], "Test Görevi")
        self.assertIn("T-1", loaded.get("tasks", {}))
        self.assertEqual(len(loaded.get("uploaded_specs", [])), 1)


if __name__ == "__main__":
    unittest.main()
