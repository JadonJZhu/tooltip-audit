import sys
sys.path.insert(0, '/home/dev/riot-projects/projects/tooltip-audit/scripts')
import check_model as C
C.MAX_TOKENS = 32000
C.PROMPT_VERSION = "v1-reasoning"
orig = C.request_body
def rb(*a, **k):
    b = orig(*a, **k); b["reasoning"] = {"enabled": True}; b["max_tokens"] = 32000; return b
C.request_body = rb
sys.exit(C.main(sys.argv[1:]))
