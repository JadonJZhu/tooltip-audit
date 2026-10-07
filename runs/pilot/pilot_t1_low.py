# Reasoning-on pilot, setting E of the 2026-10-07 diagnostic: temperature 1.0, low reasoning effort, prompt v1.
import sys
sys.path.insert(0, '/home/dev/riot-projects/projects/tooltip-audit/scripts')
import check_model as C
C.MAX_TOKENS = 32000
C.PROMPT_VERSION = "v1-t1-low"
orig = C.request_body
def rb(*a, **k):
    b = orig(*a, **k); b["temperature"] = 1.0; b["reasoning"] = {"effort": "low"}; b["max_tokens"] = 32000; return b
C.request_body = rb
sys.exit(C.main(sys.argv[1:]))
