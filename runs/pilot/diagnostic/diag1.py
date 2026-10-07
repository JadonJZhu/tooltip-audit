import sys, json, urllib.request, concurrent.futures, collections
sys.path.insert(0, '/home/dev/riot-projects/projects/tooltip-audit/scripts')
import check_model as C
S = '/tmp/claude-1001/-home-dev-riot-projects/32a3e794-7a77-4026-ac4f-4ef3dff4d946/scratchpad'
key = C.load_key()
recs = [json.loads(l) for l in open(S + '/fail10.jsonl')]
VARIANTS = {'A_now': (0, True), 'B_temp06': (0.6, True), 'C_nostrict': (0, False), 'D_both': (0.6, False)}
def body(inp, temp, strict):
    b = C.request_body(inp, 'strong', backup=True)
    b['temperature'] = temp; b['reasoning'] = {'enabled': True}; b['max_tokens'] = 32000
    if not strict:
        b.pop('response_format', None); b['provider']['require_parameters'] = False
    return b
def run(job):
    v, inp = job; temp, strict = VARIANTS[v]
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', json.dumps(body(inp, temp, strict)).encode(),
                                 {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=1800))
    except Exception as e:
        return {'v': v, 'id': inp['id'], 'error': repr(e)[:300]}
    ch = d['choices'][0]; m = ch['message']
    return {'v': v, 'id': inp['id'], 'provider': d.get('provider'), 'finish': ch.get('finish_reason'), 'native_finish': ch.get('native_finish_reason'),
            'content': m.get('content'), 'reasoning': m.get('reasoning'), 'usage': d.get('usage')}
jobs = [(v, r) for v in VARIANTS for r in recs]
with concurrent.futures.ThreadPoolExecutor(40) as ex, open(S + '/diag.jsonl', 'w') as f:
    for res in ex.map(run, jobs):
        f.write(json.dumps(res) + '\n'); f.flush()
