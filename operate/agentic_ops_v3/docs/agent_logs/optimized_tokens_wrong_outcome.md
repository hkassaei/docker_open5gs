## Good
Token consumption went down by 85%.

## Bad
Even though transport specialist didcorrectly point to the issue, somehow the synthesis agent decided to ignored it in favor of the more verbose ims specialist findings.

## Ugly

Apparenly, he who generates larger volume of presumptions gets the vote of confidence from the synthesis agent!

## Details

  Transport Specialist (correct answer, too short)

  ▎ The P-CSCF is configured to send large SIP INVITE messages via TCP (udp_mtu_try_proto = TCP). However, the destination e2e_ue2 only listens for SIP traffic on UDP port 5060, and not on TCP. This mismatch
  means that if an INVITE from UE1 is large enough to trigger the P-CSCF's TCP transmission, it will be silently dropped by UE2, preventing the call from establishing.

  3 sentences. Correct root cause. But no raw_evidence_context, no explicit recommendation, no causal chain to the observed 500 error. It states the mismatch exists but doesn't connect it to the symptoms the
  other agents found.

  IMS Specialist (wrong answer, very detailed)

  ▎ There is a misconfiguration in the I-CSCF's Diameter XML configuration file... LIRs are timing out... The fault therefore lies in an application-level parameter within the I-CSCF's XML file, such as an
  incorrect Application-ID or Vendor-ID...

  Full paragraph with raw_evidence_context block quoting 4 specific evidence lines (config paths, timeout metric, error message). Admits "my tools cannot read this specific XML file" but still projects
  confidence through volume and structure.

  Core Specialist

  Not found — it produced no finding_core output. It ran (18K tokens, 7 tool calls) but apparently its output didn't get stored in state. Likely its output_key="finding_core" text was empty or the agent didn't
   produce a final text response.

  Why Synthesis Got It Wrong

  The asymmetry is clear. The IMS Specialist gave Synthesis:
  - A structured theory with named config files
  - 4 lines of quoted evidence
  - A specific metric (uar_timeouts = 1.0)
  - A causal chain (even though it's wrong)

  The Transport Specialist gave Synthesis:
  - A correct 3-sentence finding
  - No raw evidence block
  - No connection to the 500 error everyone else saw
  - No explicit fix recommendation

  Synthesis chose the finding with more supporting structure, not the one with better evidence. The fix is making the Transport Specialist's output match the IMS Specialist's format — include
  raw_evidence_context, connect the TCP mismatch to the cascading 500, and state the specific fix.

