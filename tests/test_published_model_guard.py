from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_support import load_module, run_python


guard = load_module("hooks/published_model_guard.py", "published_model_guard")

PROJECT = {
    "dbt_project.yml": (
        "name: shop\n"
        "model-paths: ['models']\n"
        "models:\n"
        "  shop:\n"
        "    marts:\n"
        "      +materialized: table\n"
        "      shared:\n"
        "        +access: public\n"
    ),
    "models/marts/fct_settlements.sql": "select settlement_id from {{ ref('int_settlement_lines') }}\n",
    "models/intermediate/int_settlement_lines.sql": "select settlement_id from {{ ref('stg_settlements') }}\n",
    "models/staging/stg_settlements.sql": "select 1 as settlement_id\n",
    "models/marts/fct_internal.sql": "select 1 as id\n",
    "models/marts/fct_exposed.sql": "select 1 as id\n",
    "models/marts/fct_looked_at.sql": "select 1 as id\n",
    "models/marts/shared/dim_accounts.sql": "select 1 as account_id\n",
    "models/marts/_marts.yml": (
        "version: 2\n"
        "models:\n"
        "  - name: fct_settlements\n"
        "    config:\n"
        "      contract:\n"
        "        enforced: true\n"
        "    columns:\n"
        "      - name: settlement_id\n"
        "        data_tests:\n"
        "          - relationships:\n"
        "              to: ref('fct_internal')\n"
        "              field: id\n"
        "  - name: fct_internal\n"
        "    description: Internal only.\n"
    ),
    "models/exposures.yml": (
        "version: 2\n"
        "exposures:\n"
        "  - name: payouts\n"
        "    type: application\n"
        "    depends_on:\n"
        "      - ref('fct_exposed')\n"
    ),
    "looker/views/looked_at.view.lkml": "view: looked_at {\n  sql_table_name: analytics.fct_looked_at ;;\n}\n",
}


class PublishedModelGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        for relative, content in PROJECT.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.transcript = Path(self.tmp.name) / "transcript.jsonl"
        self.say("Change the settlement amount.")
        state = patch.object(guard, "STATE_DIR", Path(self.tmp.name) / "state")
        state.start()
        self.addCleanup(state.stop)
        self.addCleanup(self.tmp.cleanup)

    def say(self, text: str) -> None:
        with self.transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"role": "user", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
            handle.write(json.dumps({"role": "assistant", "message": {"content": []}}) + "\n")

    def payload(self, tool: str, tool_input: dict, conversation: str = "c-1") -> dict:
        return {
            "hook_event_name": "preToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "conversation_id": conversation,
            "transcript_path": str(self.transcript),
            "workspace_roots": [str(self.root)],
        }

    def write(self, relative: str, **extra) -> dict:
        target = str(self.root / relative)
        return guard.decide(self.payload("Write", {"file_path": target, "content": "select 2\n"}, **extra))

    def shell(self, command: str) -> dict:
        return guard.decide(self.payload("Shell", {"command": command, "cwd": str(self.root)}))

    def test_a_contracted_model_pauses_until_the_requester_replies(self) -> None:
        first = self.write("models/marts/fct_settlements.sql")
        self.assertEqual(first["permission"], "deny")
        self.assertIn("an enforced contract", first["agent_message"])
        self.assertIn("by any other route", first["agent_message"])

        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "deny")

        self.say("Approved, go ahead.")
        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "allow")
        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "allow")

    def test_each_kind_of_consumer_makes_a_model_published(self) -> None:
        cases = {
            "models/marts/fct_exposed.sql": "exposure in models/exposures.yml",
            "models/marts/fct_looked_at.sql": "LookML in looker/views/looked_at.view.lkml",
            "models/marts/shared/dim_accounts.sql": "public access set for its folder in dbt_project.yml",
        }
        for relative, reason in cases.items():
            with self.subTest(relative=relative):
                decision = self.write(relative)
                self.assertEqual(decision["permission"], "deny")
                self.assertIn(reason, decision["agent_message"])

    def test_unpublished_new_and_non_model_files_are_not_guarded(self) -> None:
        """A relationships test points at a model; it does not consume it."""
        for relative in (
            "models/marts/fct_internal.sql",
            "models/marts/shared/dim_new_thing.sql",
            "models/marts/_marts.yml",
            "tests/assert_settlements_positive.sql",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(self.write(relative)["permission"], "allow")

    def test_shell_writes_are_guarded_and_reads_are_not(self) -> None:
        for command in (
            "echo 'select 3' >> models/marts/fct_sett*.sql",
            "sed -i '' 's/1/2/' models/marts/fct_settlements.sql",
            "cp /tmp/new.sql models/marts/fct_settlements.sql",
            "python3 -c \"open('models/marts/fct_settlements.sql','w').write('x')\"",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.shell(command)["permission"], "deny")
        for command in (
            "cat models/marts/fct_settlements.sql",
            "sed -n 1,20p models/marts/fct_settlements.sql 2>/dev/null",
            "rg settlement_id models/marts/fct_settlements.sql | head -5",
            "git diff models/marts/fct_settlements.sql",
        ):
            with self.subTest(command=command):
                self.assertEqual(self.shell(command)["permission"], "allow")

    def test_an_unreadable_reply_record_allows_with_a_warning(self) -> None:
        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "deny")
        self.transcript.unlink()
        decision = self.write("models/marts/fct_settlements.sql")
        self.assertEqual(decision["permission"], "allow")
        self.assertEqual(decision["reason_code"], "guard-unconfirmed")
        self.assertIn("could not confirm a reply", decision["user_message"])

    def test_a_slow_project_scan_allows_with_a_warning(self) -> None:
        with patch.object(guard, "SCAN_BUDGET_SECONDS", -1):
            decision = self.write("models/marts/fct_settlements.sql")
        self.assertEqual(decision["permission"], "allow")
        self.assertEqual(decision["reason_code"], "guard-over-budget")

    def test_projects_can_turn_the_guard_off(self) -> None:
        (self.root / ".ae").mkdir()
        (self.root / ".ae" / "project.yml").write_text("guard_published_models: false\n", encoding="utf-8")
        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "allow")

    def test_other_tools_and_broken_input_never_block(self) -> None:
        read = guard.decide(self.payload("Read", {"file_path": str(self.root / "models/marts/fct_settlements.sql")}))
        self.assertEqual(read["permission"], "allow")
        result = run_python("hooks/published_model_guard.py", stdin="{not json")
        self.assertEqual(result.returncode, 0)
        decision = json.loads(result.stdout)
        self.assertEqual(decision["permission"], "allow")
        self.assertEqual(decision["reason_code"], "guard-error")

    def prompt(self, text: str, conversation: str = "c-1") -> None:
        guard.record_prompt(
            {"hook_event_name": "beforeSubmitPrompt", "prompt": text, "conversation_id": conversation}
        )

    def test_requests_that_change_meaning_are_told_apart_from_ones_that_change_the_build(self) -> None:
        redefining = (
            "In fct_orders, change net_revenue so refunds are subtracted.",
            "rename gmv to gross_merchandise_value",
            "Units on notice should count as vacant from now on.",
            "Drop the legacy_status column from dim_customers.",
            "Update the churn definition to exclude paused accounts.",
            "Treat trial users as inactive in active_users.",
            "Change customer_id to a string type.",
            "Refactor it into layers. While you're there, rename adr to average_daily_rate.",
            "filter lapsed members out of dim_members, the team only wants current ones. don't touch the db.",
            "Exclude test accounts from fct_orders.",
            "add reopen_rate (reopened/closed claims) + make avg_days_to_close skip reopened claims.",
            "Add a reopen_rate metric, and change avg_days_to_close so it leaves out claims that were reopened.",
            "The reopened ones drag avg_days_to_close up, so could you have that metric leave them out?",
        )
        building = (
            "Make fct_usage incremental; the rebuild takes two hours.",
            "Refactor fct_revenue into staging and intermediate layers without changing its output.",
            "Add docs and tests for fct_loans.",
            "Change the materialization so it builds incrementally.",
            "Add a new column for the regional manager.",
            "Build a new mart with tests and documentation.",
            "Review this model before I merge it.",
            "2 new metrics: avg kg per shipment, late delivery share. our metric conventions.",
            "Make fct_usage incremental. Don't touch the warehouse.",
            "They pull two numbers by hand and I'd love to stop doing that. Can we get trip distance into the semantic layer?",
            "Make fct_usage incremental and skip the tests for now.",
        )
        for text in redefining:
            with self.subTest(text=text):
                self.assertTrue(guard.asks_to_redefine(text))
        for text in building:
            with self.subTest(text=text):
                self.assertFalse(guard.asks_to_redefine(text))

    def test_request_reading_holds_across_hundreds_of_phrasings(self) -> None:
        corpus = json.loads((Path(__file__).parent / "fixtures" / "guard_requests.json").read_text())
        missed = [text for text in corpus["meaning"] if not guard.asks_to_redefine(text)]
        paused = [text for text in corpus["build"] if guard.asks_to_redefine(text)]
        # A missed meaning change still meets the rules; a false pause costs one reply.
        self.assertLessEqual(len(missed) / len(corpus["meaning"]), 0.015, missed)
        self.assertLessEqual(len(paused) / len(corpus["build"]), 0.03, paused)

    def test_a_redefinition_stays_paused_through_retries_until_a_real_reply(self) -> None:
        self.prompt("Change settlement_id so it counts reversed settlements. Go ahead.")
        for _ in range(3):
            decision = self.write("models/marts/fct_settlements.sql")
            self.assertEqual(decision["permission"], "deny")
            self.assertIn("Retrying will be denied", decision["agent_message"])
        self.assertEqual(self.write("models/marts/_marts.yml")["permission"], "deny")
        self.assertEqual(
            self.shell("sed -i '' 's/1/2/' models/marts/fct_settlements.sql")["permission"], "deny"
        )

        self.prompt("Approved.")
        self.assertEqual(self.write("models/marts/fct_settlements.sql")["permission"], "allow")
        self.assertEqual(self.write("models/marts/_marts.yml")["permission"], "allow")

    def test_a_redefinition_cannot_go_around_the_model_through_what_feeds_or_reads_it(self) -> None:
        semantic = self.root / "models/semantic/sem_settlements.yml"
        semantic.parent.mkdir(parents=True)
        semantic.write_text(
            "semantic_models:\n  - name: settlements\n    model: ref('fct_internal')\n", encoding="utf-8"
        )
        self.prompt("Units on notice should count as vacant from now on.")
        for relative in (
            "models/semantic/sem_settlements.yml",
            "looker/views/looked_at.view.lkml",
        ):
            with self.subTest(relative=relative):
                self.assertEqual(self.write(relative)["permission"], "deny")
        self.assertIn("feeds the published model `fct_settlements`",
                      self.write("models/staging/stg_settlements.sql")["agent_message"])
        self.assertEqual(self.write("models/intermediate/int_settlement_lines.sql")["permission"], "deny")
        (self.root / "models/marts/fct_scratch.sql").write_text("select 1 as id\n", encoding="utf-8")
        self.assertEqual(self.write("models/marts/fct_scratch.sql")["permission"], "allow")

        self.prompt("Make the staging layer incremental.")
        self.assertEqual(self.write("models/staging/stg_settlements.sql")["permission"], "allow")

    def test_a_held_rename_lets_the_rest_of_the_request_through(self) -> None:
        self.prompt(
            "Refactor fct_settlements into layers without changing its output. "
            "While you're in there, rename settlement_id to settlement_key."
        )
        target = str(self.root / "models/marts/fct_settlements.sql")

        def write(content: str) -> str:
            return guard.decide(self.payload("Write", {"file_path": target, "content": content}))["permission"]

        self.assertEqual(write("select settlement_id from {{ ref('int_settlement_lines') }} -- layered\n"), "allow")
        self.assertEqual(write("select settlement_id as settlement_key from {{ ref('int_settlement_lines') }}\n"), "deny")
        self.assertEqual(write("select 1 as id\n"), "deny")
        self.assertEqual(self.shell("sed -i '' 's/1/2/' models/marts/fct_settlements.sql")["permission"], "deny")
        stored = "".join(path.read_text() for path in (Path(self.tmp.name) / "state").glob("*"))
        self.assertNotIn("settlement_key", stored)

    def test_a_held_rename_that_was_folded_into_the_edit_says_how_to_finish_the_rest(self) -> None:
        self.prompt(
            "Refactor fct_settlements into layers without changing its output. "
            "While you're in there, rename settlement_id to settlement_key."
        )
        target = str(self.root / "models/marts/fct_settlements.sql")
        folded = guard.decide(
            self.payload("Write", {"file_path": target, "content": "select settlement_id as settlement_key from x\n"})
        )
        self.assertEqual(folded["permission"], "deny")
        self.assertEqual(folded["reason_code"], "published-name-change")
        self.assertIn("under its current name", folded["agent_message"])
        kept = guard.decide(
            self.payload("Write", {"file_path": target, "content": "select settlement_id from {{ ref('int_settlement_lines') }}\n"})
        )
        self.assertEqual(kept["permission"], "allow")

    def test_a_stated_approval_shows_the_consumers_once_then_lets_the_edit_through(self) -> None:
        self.prompt(
            "Finance and the settlements team have both signed off: count reversed settlements as zero in "
            "fct_settlements. Go ahead and make the edit."
        )
        target = str(self.root / "models/marts/fct_settlements.sql")

        def write() -> dict[str, str]:
            return guard.decide(self.payload("Write", {"file_path": target, "content": "select 1 as id\n"}))

        first = write()
        self.assertEqual(first["permission"], "deny")
        self.assertEqual(first["reason_code"], "approval-check")
        self.assertIn("fct_settlements", first["agent_message"])
        self.assertIn("only the consumers whose owners the request names", first["agent_message"])
        second = write()
        self.assertEqual(second["permission"], "allow")
        self.assertEqual(second["reason_code"], "approval-claimed")
        self.prompt("Also count voided settlements as zero; finance has already approved that too.")
        self.assertEqual(write()["permission"], "deny")

    def test_an_approval_that_has_not_happened_still_pauses(self) -> None:
        for prompt in (
            "Finance hasn't signed off yet, but count reversed settlements as zero in fct_settlements.",
            "Count reversed settlements as zero in fct_settlements before finance signs off.",
            "Count reversed settlements as zero in fct_settlements once finance has approved it.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(guard.claims_approval(prompt))
        self.assertTrue(guard.claims_approval("Dana gave the go-ahead: count reversed settlements as zero."))
        self.assertFalse(guard.claims_approval("Filter fct_settlements on approved_at instead of created_at."))

    def test_only_a_pure_rename_or_removal_is_held_by_name(self) -> None:
        self.assertIsNotNone(guard.held_names("Refactor it into layers. Also rename adr_usd to average_daily_rate_usd."))
        self.assertIsNotNone(guard.held_names("clean up the CTEs and drop legacy_flag"))
        self.assertIsNone(guard.held_names("rename gmv to gross_merchandise_value and exclude test orders"))
        self.assertIsNone(guard.held_names("Units on notice should count as vacant."))
        self.assertIsNone(guard.held_names("rename adr_usd to average_daily_rate_usd"))

    def test_a_properties_edit_is_guarded_only_for_the_model_blocks_it_changes(self) -> None:
        self.prompt("Drop fct_internal, nothing reads it anymore.")
        target = self.root / "models/marts/_marts.yml"
        text = target.read_text(encoding="utf-8")

        def replace(old: str, new: str) -> dict[str, str]:
            return guard.decide(
                self.payload("StrReplace", {"path": str(target), "old_string": old, "new_string": new})
            )

        removed = replace("  - name: fct_internal\n    description: Internal only.\n", "")
        self.assertEqual(removed["permission"], "allow")
        touched = replace("        enforced: true\n", "        enforced: false\n")
        self.assertEqual(touched["permission"], "deny")
        self.assertIn("fct_settlements", touched["agent_message"])
        self.assertEqual(self.shell(f"python3 -c \"open('{target}', 'w').write('')\"")["permission"], "deny")
        self.assertEqual(target.read_text(encoding="utf-8"), text)

    def test_unlisting_a_model_from_an_exposure_pauses_like_editing_it(self) -> None:
        self.prompt("Drop fct_exposed, nothing reads it anymore.")
        target = str(self.root / "models/exposures.yml")

        def replace(old: str, new: str) -> dict[str, str]:
            return guard.decide(self.payload("StrReplace", {"path": target, "old_string": old, "new_string": new}))

        added = replace("      - ref('fct_exposed')\n", "      - ref('fct_exposed')\n      - ref('fct_internal')\n")
        self.assertEqual(added["permission"], "allow")
        dropped = replace("      - ref('fct_exposed')\n", "")
        self.assertEqual(dropped["permission"], "deny")
        self.assertIn("fct_exposed", dropped["agent_message"])
        self.assertIn("stops listing", dropped["agent_message"])

    def test_reinterpreting_a_read_snapshot_pauses_however_the_request_is_phrased(self) -> None:
        snapshot = self.root / "snapshots/snap_settlements.sql"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(
            "{% snapshot snap_settlements %}\n"
            "{{ config(unique_key='settlement_id', strategy='check', check_cols=['status']) }}\n"
            "select * from {{ ref('stg_settlements') }}\n"
            "{% endsnapshot %}\n",
            encoding="utf-8",
        )
        reader = self.root / "models/marts/fct_settlement_history.sql"
        reader.write_text("select * from {{ ref('snap_settlements') }}\n", encoding="utf-8")
        self.prompt("Fix the duplicates in snap_settlements and document it.")

        def replace(old: str, new: str) -> dict[str, str]:
            return guard.decide(self.payload("StrReplace", {"path": str(snapshot), "old_string": old, "new_string": new}))

        rekey = replace("unique_key='settlement_id'", "unique_key=['region', 'settlement_id']")
        self.assertEqual(rekey["permission"], "deny")
        self.assertEqual(rekey["reason_code"], "snapshot-history-change")
        self.assertIn("models/marts/fct_settlement_history.sql", rekey["agent_message"])
        self.assertEqual(replace("check_cols=['status']", "check_cols=['status', 'amount']")["permission"], "allow")
        self.assertEqual(replace("check_cols=['status']", "check_cols=[]")["permission"], "deny")

        reader.unlink()
        self.assertEqual(replace("unique_key='settlement_id'", "unique_key='settlement_key'")["permission"], "allow")

    def test_building_requests_edit_published_models_without_pausing(self) -> None:
        self.prompt("Make fct_settlements incremental and document the lookback window.")
        for relative in ("models/marts/fct_settlements.sql", "models/marts/_marts.yml"):
            with self.subTest(relative=relative):
                decision = self.write(relative)
                self.assertEqual(decision["permission"], "allow")
                self.assertEqual(decision["reason_code"], "not-a-redefinition")

    def test_the_message_hook_lets_every_message_through_and_stores_no_text(self) -> None:
        result = run_python(
            "hooks/published_model_guard.py",
            stdin=json.dumps(
                {"hook_event_name": "beforeSubmitPrompt", "prompt": "rename secret_column_xyz", "conversation_id": "c-9"}
            ),
            env={"TMPDIR": self.tmp.name},
        )
        self.assertEqual(json.loads(result.stdout), {"continue": True})
        stored = "".join(path.read_text() for path in Path(self.tmp.name).rglob("ae-toolkit-guard/*"))
        self.assertIn("_prompts", stored)
        self.assertNotIn("secret_column_xyz", stored)

    def test_the_gate_is_wired_for_edits_and_shell_and_records_no_identity(self) -> None:
        from test_support import PLUGIN_ROOT, read_json

        entries = read_json(PLUGIN_ROOT / "hooks" / "hooks.json")["hooks"]["preToolUse"]
        command = entries[0]["command"]
        self.assertIn("published_model_guard.py", command)
        for tool in ("Write", "Delete", "Shell"):
            self.assertIn(tool, entries[0]["matcher"])

        payload = self.payload("Write", {"file_path": str(self.root / "models/marts/fct_settlements.sql")})
        payload["user_email"] = "someone@example.invalid"
        guard.decide(payload)
        stored = "".join(path.read_text() for path in (Path(self.tmp.name) / "state").glob("*.json"))
        self.assertNotIn("example.invalid", stored)
        self.assertNotIn("c-1", stored)


if __name__ == "__main__":
    unittest.main()
