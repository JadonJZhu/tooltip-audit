import sys, json, urllib.request, concurrent.futures, collections
sys.path.insert(0, '/home/dev/riot-projects/projects/tooltip-audit/scripts')
import check_model as C
S = '/tmp/claude-1001/-home-dev-riot-projects/32a3e794-7a77-4026-ac4f-4ef3dff4d946/scratchpad'
key = C.load_key()
recs = [json.loads(l) for l in open(S + '/fail10.jsonl')]
DECISIVE = '''

How to work: go through the placeholders and typed numbers once, in order. For each one, find the value it should agree with, decide agree or disagree, and move on. Do not come back to a decision once made. If you cannot name a specific value in the record that differs, it agrees. When you reach the end, answer.'''
VARIANTS = {'E_t1_low': (1.0, 'low', False), 'F_t1_low_decisive': (1.0, 'low', True), 'G_t1_default_decisive': (1.0, None, True)}
def body(inp, temp, effort, decisive):
    b = C.request_body(inp, 'strong', backup=True)
    b['temperature'] = temp; b['reasoning'] = {'effort': effort} if effort else {'enabled': True}; b['max_tokens'] = 32000
    if decisive: b['messages'][0]['content'] = C.PROMPT + DECISIVE
    return b
def run(job):
    v, inp = job; temp, effort, decisive = VARIANTS[v]
    req = urllib.request.Request('https://openrouter.ai/api/v1/chat/completions', json.dumps(body(inp, temp, effort, decisive)).encode(),
                                 {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=1800))
    except Exception as e:
        return {'v': v, 'id': inp['id'], 'error': repr(e)[:300]}
    ch = d['choices'][0]; m = ch['message']
    return {'v': v, 'id': inp['id'], 'provider': d.get('provider'), 'finish': ch.get('finish_reason'), 'native_finish': ch.get('native_finish_reason'),
            'content': m.get('content'), 'reasoning': m.get('reasoning'), 'usage': d.get('usage')}
jobs = [(v, r) for v in VARIANTS for r in recs]
with concurrent.futures.ThreadPoolExecutor(40) as ex, open(S + '/diag2.jsonl', 'w') as f:
    for res in ex.map(run, jobs):
        f.write(json.dumps(res) + '\n'); f.flush()
