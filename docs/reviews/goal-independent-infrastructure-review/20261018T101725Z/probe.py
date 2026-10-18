import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path('/Users/vinay2047/.codex/worktrees/4f55/FalkorDB_agent')
sys.path.insert(0, str(ROOT / 'evals'))
from confirmatory.corpus_export import export_corpus
from confirmatory.plaintext_tools import PlaintextTools

OUT = Path(__file__).resolve().parent
REPO = OUT / 'synthetic-attempt2'
REPO.mkdir(exist_ok=False)
ENV = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
ENV.update(GIT_AUTHOR_NAME='Independent Reviewer', GIT_AUTHOR_EMAIL='review@example.invalid',
           GIT_COMMITTER_NAME='Independent Reviewer', GIT_COMMITTER_EMAIL='review@example.invalid',
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
def git(*args, data=None):
    return subprocess.check_output(['git', '-C', str(REPO), *args], input=data, env=ENV).strip()

paths = ['evals/confirmatory/corpus_export.py', 'evals/confirmatory/plaintext_tools.py',
         'tests/test_confirmatory_corpus.py', 'tests/test_confirmatory_plaintext.py']
hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
git('init', '-q')
(REPO / 'unicode.py').write_bytes("x = 'left\u2028right'\nneedle = 2\n".encode())
(REPO / 'long.py').write_text('#' + 'a' * 300000 + '\n')
(REPO / 'no_final_newline.py').write_bytes(b'a')
git('add', '.')
tree = git('write-tree').decode()
old = git('-c', 'i18n.commitEncoding=ISO-8859-1', 'commit-tree', tree,
          data=b'plain-ascii-subject\n\nnon-UTF8 byte: \xff\n').decode()
git('update-ref', 'refs/heads/main', old)
git('tag', '-a', 'release', old, '-m', 'ANNOTATED_TAG_ONLY_EVIDENCE')
(REPO / 'no_final_newline.py').write_bytes(b'b')
git('add', '.')
new = git('commit-tree', git('write-tree').decode(), '-p', old, data=b'new state\n').decode()
git('update-ref', 'refs/heads/main', new)
receipt = export_corpus(REPO, {'schema': 'source-corpus-spec/v1', 'repository': 'synthetic-review',
    'roots': [new], 'include': ['*.py'], 'exclude': []}, OUT / 'export-attempt2')
tools = PlaintextTools(OUT / 'export-attempt2')
rows = [json.loads(x) for x in (OUT / 'export-attempt2/corpus.jsonl').read_bytes().splitlines()]
tag = next(x for x in rows if x.get('name') == 'refs/tags/release')
line = tools.search(new, 'needle')['items'][0]
binary_commit = tools.show_commit(old)
patch = tools.diff(old, new, 'no_final_newline.py')['patch']
parse_patch = subprocess.run(['git', 'apply', '--numstat', '-'], input=patch.encode(),
                             capture_output=True, env=ENV)
report = {'schema': 'independent-source-review-probes/v1', 'source_hashes': hashes,
    'synthetic_only': True, 'heldout_access': False, 'old': old, 'new': new,
    'line_provenance': {'source_lf_line_count': 2,
        'needle_expected_line': 2, 'needle_returned_line': line['citation']['start_line'],
        'read_line_2': tools.read_file(new, 'unicode.py', start=2, end=2),
        'full_read_total_lines': tools.read_file(new, 'unicode.py')['total_lines']},
    'commit_search': {'raw_encoding': binary_commit['encoding'],
        'raw_contains_subject': b'plain-ascii-subject' in base64.b64decode(binary_commit['content']),
        'subject_query_total': tools.log(new, text='plain-ascii-subject')['total'],
        'query_complete': tools.log(new, text='plain-ascii-subject')['complete']},
    'tag_access': {'export_has_tag_message': 'ANNOTATED_TAG_ONLY_EVIDENCE' in tag['tag_chain'][0]['content'],
        'loader_ref_value_type': type(tools.refs['refs/tags/release']).__name__,
        'public_methods': [n for n in dir(tools) if not n.startswith('_') and callable(getattr(tools, n))],
        'log_tag_message_matches': tools.log(new, text='ANNOTATED_TAG_ONLY_EVIDENCE')['total']},
    'large_line': {'read_content_bytes': len(tools.read_file(new, 'long.py', start=1, end=1)['content'].encode()),
        'search_limit_1_content_bytes': len(tools.search(new, 'aaa', limit=1)['items'][0]['content'].encode())},
    'no_newline_patch': {'patch': patch, 'git_apply_numstat_returncode': parse_patch.returncode,
        'git_apply_stderr': parse_patch.stderr.decode()},
    'source_unchanged_after': all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == sha for p, sha in hashes.items())}
(OUT / 'probe-results.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
