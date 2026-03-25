"""Unit tests for the _filter_notable_logs function in symptom_observer.

This is the core signal detection logic — it decides whether symptoms
were detected during a chaos episode. No Docker needed.
"""

from agentic_chaos.agents.symptom_observer import _filter_notable_logs


class TestFilterNotableLogs:
    def test_detects_error_keyword(self):
        logs = {"pcscf": ["INFO: all good", "ERROR: connection refused"]}
        result = _filter_notable_logs(logs)
        assert "pcscf" in result
        assert len(result["pcscf"]) == 1
        assert "connection refused" in result["pcscf"][0]

    def test_detects_sip_408_timeout(self):
        logs = {"e2e_ue1": ["Registration failed: 408 Request Timeout"]}
        result = _filter_notable_logs(logs)
        assert "e2e_ue1" in result

    def test_detects_sip_500_error(self):
        logs = {"scscf": ["SIP/2.0 500 Internal Server Error"]}
        result = _filter_notable_logs(logs)
        assert "scscf" in result

    def test_detects_timeout_keyword(self):
        logs = {"icscf": ["transaction timeout for REGISTER"]}
        result = _filter_notable_logs(logs)
        assert "icscf" in result

    def test_detects_unreachable(self):
        logs = {"amf": ["gNB unreachable — removing association"]}
        result = _filter_notable_logs(logs)
        assert "amf" in result

    def test_detects_connection_refused(self):
        logs = {"pyhss": ["Connection refused to MySQL"]}
        result = _filter_notable_logs(logs)
        assert "pyhss" in result

    def test_excludes_allow_header_false_positive(self):
        """SIP 'Allow:' header contains methods — should not match."""
        logs = {"pcscf": [
            "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS, REGISTER",
        ]}
        result = _filter_notable_logs(logs)
        assert result == {}

    def test_excludes_sdp_unrecognised_option(self):
        """Known SMF/UPF noise line — should not match."""
        logs = {"smf": ["unrecognised option [-1] in SDP parsing"]}
        result = _filter_notable_logs(logs)
        assert result == {}

    def test_empty_logs(self):
        result = _filter_notable_logs({})
        assert result == {}

    def test_empty_lines(self):
        logs = {"amf": ["", "", ""]}
        result = _filter_notable_logs(logs)
        assert result == {}

    def test_normal_logs_not_flagged(self):
        """Regular info/debug lines should not be detected as symptoms."""
        logs = {
            "amf": [
                "[amf] INFO: NAS Security mode complete",
                "[amf] INFO: Registration complete for IMSI-001011234567891",
            ],
            "pcscf": [
                "REGISTER sip:ims.mnc001.mcc001.3gppnetwork.org",
                "SIP/2.0 200 OK",
            ],
        }
        result = _filter_notable_logs(logs)
        assert result == {}

    def test_multiple_containers_with_errors(self):
        logs = {
            "pcscf": ["ERROR: tm timeout", "INFO: ok"],
            "scscf": ["INFO: all good"],
            "nr_gnb": ["signal lost for UE"],
        }
        result = _filter_notable_logs(logs)
        assert "pcscf" in result
        assert "nr_gnb" in result
        assert "scscf" not in result  # Only INFO lines

    def test_case_insensitive_matching(self):
        """Keywords should match regardless of case."""
        logs = {"amf": ["FATAL: out of memory"]}
        result = _filter_notable_logs(logs)
        assert "amf" in result

    def test_503_service_unavailable(self):
        logs = {"icscf": ["SIP/2.0 503 Service Unavailable"]}
        result = _filter_notable_logs(logs)
        assert "icscf" in result

    def test_drop_keyword(self):
        logs = {"upf": ["GTP packet dropped — no matching session"]}
        result = _filter_notable_logs(logs)
        assert "upf" in result

    def test_lost_keyword_for_gnb(self):
        """'lost' keyword catches gNB 'signal lost' messages."""
        logs = {"nr_gnb": ["[rls] signal lost for UE"]}
        result = _filter_notable_logs(logs)
        assert "nr_gnb" in result
