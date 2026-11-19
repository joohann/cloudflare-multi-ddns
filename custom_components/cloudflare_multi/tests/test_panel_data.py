"""Unit tests for the validation and payload rules the panel relies on."""
import unittest

from _load import load

modules = load()
panel_data = modules.panel_data
const = modules.const


class FqdnTest(unittest.TestCase):
    def test_apex_is_the_zone_itself(self):
        self.assertEqual(panel_data.fqdn("example.com", "@"), "example.com")
        self.assertEqual(panel_data.fqdn("example.com", ""), "example.com")
        self.assertEqual(panel_data.fqdn("example.com", "  "), "example.com")

    def test_label_is_prefixed(self):
        self.assertEqual(panel_data.fqdn("example.com", "www"), "www.example.com")

    def test_label_is_trimmed(self):
        self.assertEqual(panel_data.fqdn("example.com", " vpn "), "vpn.example.com")


class ValidateRecordTest(unittest.TestCase):
    def test_normalises_case_and_whitespace(self):
        record = panel_data.validate_record(
            {"domain": "  Example.COM. ", "name": " www ", "record_type": "a"}
        )
        self.assertEqual(
            record, {"domain": "example.com", "name": "www", "record_type": "A"}
        )

    def test_rejects_a_domain_without_a_dot(self):
        with self.assertRaises(panel_data.ValidationError) as caught:
            panel_data.validate_record({"domain": "example", "name": "@", "record_type": "A"})
        self.assertEqual(caught.exception.code, "invalid_domain")

    def test_rejects_an_empty_name(self):
        with self.assertRaises(panel_data.ValidationError) as caught:
            panel_data.validate_record({"domain": "example.com", "name": " ", "record_type": "A"})
        self.assertEqual(caught.exception.code, "invalid_name")

    def test_rejects_an_unsupported_type(self):
        with self.assertRaises(panel_data.ValidationError) as caught:
            panel_data.validate_record(
                {"domain": "example.com", "name": "@", "record_type": "CNAME"}
            )
        self.assertEqual(caught.exception.code, "invalid_type")

    def test_rejects_a_non_object(self):
        with self.assertRaises(panel_data.ValidationError):
            panel_data.validate_record("example.com")

    def test_proxied_and_ttl_are_not_stored(self):
        """They are Cloudflare's to own; the panel only ever displays them."""
        record = panel_data.validate_record(
            {
                "domain": "example.com",
                "name": "@",
                "record_type": "A",
                "proxied": True,
                "ttl": 300,
            }
        )
        self.assertEqual(set(record), {"domain", "name", "record_type"})


class ValidateRecordsTest(unittest.TestCase):
    def test_drops_duplicates_keeping_order(self):
        records = panel_data.validate_records(
            [
                {"domain": "example.com", "name": "@", "record_type": "A"},
                {"domain": "EXAMPLE.com", "name": "@", "record_type": "a"},
                {"domain": "example.com", "name": "vpn", "record_type": "A"},
            ]
        )
        self.assertEqual([r["name"] for r in records], ["@", "vpn"])

    def test_keeps_the_same_name_in_different_zones(self):
        records = panel_data.validate_records(
            [
                {"domain": "one.com", "name": "@", "record_type": "A"},
                {"domain": "two.com", "name": "@", "record_type": "A"},
            ]
        )
        self.assertEqual([r["domain"] for r in records], ["one.com", "two.com"])

    def test_rejects_a_non_list(self):
        with self.assertRaises(panel_data.ValidationError):
            panel_data.validate_records({"domain": "example.com"})


class ValidateOptionsTest(unittest.TestCase):
    def test_only_returns_keys_that_were_sent(self):
        self.assertEqual(
            panel_data.validate_options({"update_interval": 15}), {"update_interval": 15}
        )

    def test_interval_bounds(self):
        for value in (const.MIN_UPDATE_INTERVAL_MINUTES - 1, const.MAX_UPDATE_INTERVAL_MINUTES + 1):
            with self.assertRaises(panel_data.ValidationError) as caught:
                panel_data.validate_options({"update_interval": value})
            self.assertEqual(caught.exception.code, "invalid_interval")

    def test_interval_must_be_a_number(self):
        with self.assertRaises(panel_data.ValidationError):
            panel_data.validate_options({"update_interval": "soon"})

    def test_booleans_must_be_real_booleans(self):
        with self.assertRaises(panel_data.ValidationError) as caught:
            panel_data.validate_options({"panel_enabled": "yes"})
        self.assertEqual(caught.exception.code, "invalid_boolean")

    def test_targets_are_stripped_and_deduplicated(self):
        result = panel_data.validate_options(
            {"notify_targets": [" mobile_app_a ", "mobile_app_a", "", "mobile_app_b"]}
        )
        self.assertEqual(result["notify_targets"], ["mobile_app_a", "mobile_app_b"])

    def test_records_go_through_record_validation(self):
        with self.assertRaises(panel_data.ValidationError):
            panel_data.validate_options({"records": [{"domain": "nope"}]})


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.options = {
            "records": [{"domain": "example.com", "name": "@", "record_type": "A"}],
            "update_interval": 15,
        }

    def test_public_options_fills_in_defaults(self):
        public = panel_data.public_options(self.options)
        self.assertEqual(public["update_interval"], 15)
        self.assertEqual(public["panel_enabled"], const.DEFAULT_PANEL_ENABLED)
        self.assertEqual(public["notify_targets"], [])

    def test_records_state_merges_result_and_history(self):
        key = panel_data.record_key("example.com", "@", "A")
        rows = panel_data.build_records_state(
            panel_data.public_options(self.options),
            {"records": {key: {"ip": "1.1.1.1", "status": "updated"}}},
            {key: {"previous": "0.0.0.0", "changed_at": "T1", "changes": []}},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ip"], "1.1.1.1")
        self.assertEqual(rows[0]["status"], "updated")
        self.assertEqual(rows[0]["history"]["previous"], "0.0.0.0")

    def test_records_state_carries_the_cloudflare_facts(self):
        key = panel_data.record_key("example.com", "@", "A")
        rows = panel_data.build_records_state(
            panel_data.public_options(self.options),
            {
                "records": {
                    key: {
                        "ip": "1.1.1.1",
                        "status": "ok",
                        "zone_id": "zone123",
                        "record_id": "rec456",
                        "proxied": True,
                        "ttl": 1,
                    }
                }
            },
            {},
        )
        self.assertEqual(rows[0]["zone_id"], "zone123")
        self.assertEqual(rows[0]["record_id"], "rec456")
        self.assertTrue(rows[0]["proxied"])
        self.assertEqual(rows[0]["ttl"], 1)
        self.assertEqual(rows[0]["fqdn"], "example.com")

    def test_records_state_without_a_result_yet(self):
        rows = panel_data.build_records_state(
            panel_data.public_options(self.options), None, {}
        )
        self.assertIsNone(rows[0]["status"])
        self.assertIsNone(rows[0]["zone_id"])
        self.assertIsNone(rows[0]["proxied"])
        self.assertEqual(rows[0]["history"]["changes"], [])

    def test_build_info_shape(self):
        info = panel_data.build_info(
            entry_id="abc",
            title="Cloudflare DNS",
            options=self.options,
            data=None,
            ip_history={"ipv4": {"current": "1.1.1.1", "changes": []}},
            record_history={},
            notify_targets=["mobile_app_a"],
            last_update_success=True,
        )
        self.assertEqual(info["entry_id"], "abc")
        self.assertEqual(info["name"], const.INTEGRATION_NAME)
        self.assertEqual(info["state"]["ipv4"]["current"], "1.1.1.1")
        self.assertIsNone(info["state"]["ipv6"]["current"])
        self.assertEqual(info["limits"]["record_types"], const.RECORD_TYPES)
        self.assertEqual(info["notify_targets"], ["mobile_app_a"])
        self.assertTrue(info["state"]["last_update_success"])

    def test_build_info_never_carries_the_api_token(self):
        info = panel_data.build_info(
            entry_id="abc",
            title="Cloudflare DNS",
            options={**self.options, const.CONF_API_TOKEN: "secret-token-value"},
            data=None,
            ip_history={},
            record_history={},
            notify_targets=[],
            last_update_success=True,
        )
        self.assertNotIn("secret-token-value", repr(info))
        self.assertNotIn(const.CONF_API_TOKEN, info)
        self.assertNotIn(const.CONF_API_TOKEN, info["options"])


if __name__ == "__main__":
    unittest.main()
