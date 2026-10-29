"""Offline successor staging/finalization; live Boat queries authenticate TTL absence only.

Staging requires completed rehearsal evidence, or the exact-release D4 waiver.
Neither command launches, decrypts or opens a holder. Never amend old bundles.
"""
import argparse
import copy
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import re
import shutil
import subprocess
import sys
import time

from founder_decisions import CASES, CALL_CAP, AUTHORITY, rehearsal_waiver

SOURCE_ROOT = Path(__file__).resolve().parents[1]
from launch_manifest import (HOST_FILES, REQUIRED_RELEASE as REQUIRED, RUNTIME_PATHS,
    INHERITED_HELPERS, PUBLISHER, GENERATED_HELPERS, HASH_FILE, freeze_helpers,
    collection_files, D4_HOST_FILES, FINALIZATION_INPUTS, RESTORE_METADATA, RECONCILIATION_FILES, WRAPPERS)


def launcher_files(root):
    """Audit shell references against the manifest; never use this as a copy list."""
    required = set()
    scripts = [*root.glob('factory/*.sh'), *root.glob('bin/*.sh'), root/'bin/boat-call',
               *root.glob('factory/*.py'), root/'sync-to-vm.py']
    for script in scripts:
        if not script.is_file(): continue
        for braced, plain, value in re.findall(
                r"\$(?:\{(root|here)\}|(root|here))/([^\s\"'`;|()<>]+)", script.read_text()):
            value = value.rstrip('}')  # ${BOAT_CMD:-$root/bin/hcloud-boat}
            name = value if (braced or plain) == 'root' else str(script.parent.relative_to(root)/value)
            name = os.path.normpath(name)
            if name == 'founder-ruling.json':
                # stage removes --founder-ruling-sha256: prior rulings live in the
                # collected card and must not be applied for a second time.
                policy = root/'policy.restore.pending.json'
                if not policy.exists(): policy = root/'policy.restore.json'
                if not policy.exists() or not any('--founder-ruling-sha256' in j['args']
                        for j in read(policy)['jobs'].values()): continue
            if name == 'founder-ruling.json' or name not in RUNTIME_PATHS: required.add(name)
    return required


def verify_launcher_files(root):
    referenced = launcher_files(root)
    undeclared = referenced - set(HOST_FILES) - set(RUNTIME_PATHS)
    if undeclared: raise ValueError('undeclared restore launcher input: ' + ', '.join(sorted(undeclared)))
    for name in sorted(set(HOST_FILES) | referenced):
        if '$' in name or '..' in Path(name).parts or (root/name).is_symlink() or not (root/name).is_file():
            raise ValueError('missing regular restore launcher input: ' + name)


def read(path): return json.loads(path.read_text())
def sha(path):
    if path.is_symlink() or not path.is_file(): raise ValueError('missing regular bundle input')
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()
def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n'); path.chmod(0o600)
def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob('*')) if p.is_file()}
def option(argv, flag, value):
    if argv.count(flag) != 1 or any(v.startswith(flag+'=') for v in argv):
        raise ValueError('expected one explicit ' + flag)
    argv[argv.index(flag)+1] = str(value)


def collected(old, case):
    card = read(old/'sealed'/(case+'.scorecard.json'))
    if card.get('case') != case or card.get('status') != 'stopped' or card.get('checkpoint_error'):
        raise ValueError('not a clean collected stop')
    archives = [p for suffix in ('.checkpoint.tar.gz.age', '.tar.gz.age')
                if (p := old/'sealed'/(case+suffix)).is_file() and sha(p) == card.get('sha256')]
    if not archives: raise ValueError('collected ciphertext/card generation mismatch')
    return card, archives[0]


def retirement(old, case, card, archive, *, query=subprocess.run, now=None):
    """Check actual collection and provider retirement; handwritten markers grant nothing."""
    launch, = (old/'control-home/launches').glob('*/launch.json')
    state=launch.parent
    worker, = (state/'ids').read_text().split()
    if not (state/(worker+'.collected')).is_file() or sha(archive) != card['sha256']:
        raise ValueError('collection/generation not verified')
    if card.get('r2_object') != 'vm/'+worker+'/checkpoint.tar.gz.age':
        raise ValueError('collected generation is not bound to this worker')
    base=dict(worker=worker,case=case,generation=card['sha256'],launch_sha256=sha(launch),
              public_card_sha256=sha(old/'sealed'/(case+'.scorecard.json')))
    receipts=list(old.glob('results/spend/*/'+worker+'/deletion-completion.json'))
    for path in receipts:
        value=read(path)
        if value.get('targetId')==worker and value.get('status')=='completed' and value.get('completedAt'):
            return dict(base,kind='explicit_delete',receipt_sha256=sha(path),receipt=str(path))
    # Provider readiness was recorded by the launcher, independently of any later
    # operator ttl-expired/deleted marker. Bind its ID/expiry to the creation log.
    ready, = old.glob('results/spend/*-'+worker+'.readiness.json')
    observed=read(ready)
    facts=observed.get('observed') or {}
    created=[json.loads(line) for p in state.glob('new.*') for line in p.read_text().splitlines()
             if line.startswith('{')]
    expires=facts.get('archiveAfter')
    if (observed.get('outcome')!='ready' or observed.get('worker_id')!=worker or facts.get('id')!=worker or
            not any(row.get('id')==worker and row.get('archiveAfter')==expires for row in created)):
        raise ValueError('no launch-bound provider TTL evidence')
    expiry=datetime.datetime.fromisoformat(expires.replace('Z','+00:00'))
    now=time.time() if now is None else now
    if expiry.tzinfo is None or now < expiry.timestamp(): raise ValueError('worker TTL has not elapsed')
    info=query(['boat','info',worker,'--json'],capture_output=True,text=True,timeout=60)
    try: error=json.loads(info.stdout)
    except ValueError: raise ValueError('provider absence query failed') from None
    if info.returncode==0 or error.get('code')!='not_found' or error.get('status')!=404:
        raise ValueError('provider has not authenticated worker absence')
    listing=query(['boat','list','--json'],capture_output=True,text=True,timeout=60)
    try: rows=json.loads(listing.stdout)
    except ValueError: raise ValueError('provider inventory query failed') from None
    if (listing.returncode or rows.get('pageInfo',{}).get('hasMore') is not False or
            not isinstance(rows.get('sandboxes'),list) or any(r.get('id')==worker for r in rows['sandboxes'])):
        raise ValueError('provider inventory does not prove absence')
    return dict(base,kind='ttl_expiry',archiveAfter=expires,observed_absent_at=now,
                readiness_sha256=sha(ready),creation_sha256={p.name:sha(p) for p in state.glob('new.*')},
                provider_info=error,provider_inventory=rows,deletion_receipt=None)


def stage(old, root, release, adapter, adapter_sha, rehearsal, founder_decisions=None):
    if root.exists(): raise ValueError('preserve existing bundles; choose a new destination')
    if sha(adapter)!=adapter_sha: raise ValueError('qualified adapter pin mismatch')
    api=runpy.run_path(str(adapter),run_name='successor_adapter')
    _, _, files=api['load'](release)
    proof=read(rehearsal)
    source_pin=sha(release/'source-manifest.json')
    waiver=None
    if founder_decisions is not None:
        waiver=rehearsal_waiver(read(founder_decisions),source_pin,sha(rehearsal))
        if (proof.get('status')!='PARTIAL' or proof.get('source_manifest_sha256')!=source_pin or
                proof.get('real_cases_used') is not False):
            raise ValueError('D4 requires partial exact-release rehearsal evidence; no PASS is granted')
    # D4 changes only host staging policy. Ship the original pinned worker files,
    # including staging modules/tests; freeze host updates separately.
    host_changes=set(D4_HOST_FILES) & set(files) if waiver else set()
    if not set(REQUIRED) <= set(files) or any(sha(SOURCE_ROOT/name)!=value
            for name,value in files.items() if name not in host_changes):
        raise ValueError('qualify the exact current paid-route late-gate release first')
    expected={'G2','G16','G10','G17','G11','G12','G10_interrupt_restore'}
    if not waiver and (proof.get('status')!='PASS' or proof.get('source_manifest_sha256')!=source_pin or
            set(proof.get('completed',[]))!=expected or proof.get('real_cases_used') is not False):
        raise ValueError('complete exact-release late-path rehearsal required before restaging')
    policy_path=old/'policy.restore.json'
    policy=read(policy_path)
    job_name, job = next(iter(policy['jobs'].items()))
    case=job['case']
    if case not in CASES or len(policy['jobs'])!=1: raise ValueError('not a D1 case bundle')
    card, archive = collected(old, case)
    launch, = (old/'control-home/launches').glob('*/launch.json')
    root.mkdir(mode=0o700)
    for name,digest in files.items():
        source=release/'source'/name
        if sha(source)!=digest: raise ValueError('qualified source drift')
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    shutil.copytree(release,root/'candidate-vm-canary')
    (root/'bin').mkdir(exist_ok=True)
    shutil.copy2(adapter,root/'bin/qualified-release.py')
    for name in INHERITED_HELPERS:
        shutil.copy2(old/name,root/name)
    founder=root/'founder-run.py'
    founder.write_text(founder.read_text().replace("'--hours', '9'", "'--hours', '17'"))
    # Use the maintained publisher, rather than inheriting obsolete case-specific
    # ruling dependencies and fixed backup names from an older bundle.
    for target, source in PUBLISHER.items():
        shutil.copy2(SOURCE_ROOT/source,root/target)
    args=job['args']
    if '--founder-ruling-sha256' in args:
        index=args.index('--founder-ruling-sha256');del args[index:index+2]
    for flag,value in (('--qualified-release',root/'candidate-vm-canary'),('--max-total-calls',CALL_CAP),
                       ('--ttl-hours',16),('--max-spend','0.75')): option(args,flag,value)
    job.update(max_calls=CALL_CAP,known_worker_ids=[])
    policy.update(root=str(root),jobs={job_name:job})
    save(root/'policy.restore.pending.json',policy)
    save(root/'restore-config.json',dict(case=case,job=job_name,round_limit=CASES[case],case_budget=70,
        max_total_calls=CALL_CAP,ttl_hours=16,finalization_required=True))
    save(root/'source-binding.json',dict(source=str(old),policy_sha256=sha(policy_path),
        launch_sha256=sha(launch),generation=card['sha256'],public_card_sha256=sha(old/'sealed'/(case+'.scorecard.json')),
        source_manifest_sha256=sha(release/'source-manifest.json'),rehearsal_sha256=sha(rehearsal)))
    shutil.copy2(rehearsal,root/'rehearsal.json')
    # Host helpers can be outside the qualified worker payload. The manifest
    # selects them; the reference sweep only catches undeclared dependencies.
    for name in HOST_FILES:
        if name == HASH_FILE or (root/name).exists(): continue
        source=SOURCE_ROOT/name
        sha(source)
        target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    freeze_helpers(root)
    verify_launcher_files(root)
    if waiver:
        shutil.copy2(founder_decisions,root/'founder-decisions.json')
        for name in sorted(host_changes):
            target='host-tools/'+Path(name).name
            (root/'host-tools').mkdir(exist_ok=True)
            shutil.copy2(SOURCE_ROOT/name,root/target)
        binding=read(root/'source-binding.json')
        binding.update(founder_decisions_sha256=sha(root/'founder-decisions.json'),
            rehearsal_authorization='D4',d4_record_sha256=read(founder_decisions)['D4']['record_sha256'])
        save(root/'source-binding.json',binding)
    save(root/'PREPARATION-BLOCKED.json',dict(reason='Finalize from verified collected generation and retirement before launch'))
    for name,command in WRAPPERS.items():
        (root/name).write_text("import sys\nfrom pathlib import Path\nroot=Path(__file__).resolve().parent\nsys.path.insert(0,str(root/'factory'))\n"+
            ("sys.path.insert(0,str(root/'host-tools'))\n" if waiver else '')+
            "import restore_bundle\nrestore_bundle."+command+"(root)\n")
    save(root/'build.json',dict(source_sha256=files,candidate_sha256=inventory(root/'candidate-vm-canary'),
        helper_sha256={name:sha(root/name) for name in (*HOST_FILES, *INHERITED_HELPERS,
            *PUBLISHER, *GENERATED_HELPERS,
            *(name for name in RESTORE_METADATA if (root/name).exists()),
            *('host-tools/'+Path(name).name for name in host_changes))},launch_ready=False))


def verify_source(root):
    verify_launcher_files(root)
    build=read(root/'build.json')
    for name,value in {**build['source_sha256'],**build['helper_sha256']}.items():
        if sha(root/name)!=value: raise ValueError('frozen source/helper changed')
    if inventory(root/'candidate-vm-canary')!=build['candidate_sha256']:
        raise ValueError('qualified candidate changed')
    binding=read(root/'source-binding.json')
    if binding.get('rehearsal_authorization')=='D4':
        rehearsal_waiver(read(root/'founder-decisions.json'),binding['source_manifest_sha256'],sha(root/'rehearsal.json'))
    return build


def reconcile_failed_launch(root, failed, receipts_path):
    """Retain a pre-restore failure's receipts; explain its generation in policy.

    This does not authorize reuse of the failed bundle or grant case allowances.
    Only unchanged sealed inputs and completed disposal qualify.
    """
    build=verify_source(root)
    if build.get('launch_ready'): raise ValueError('reconcile before finalization')
    binding=read(root/'source-binding.json');source=Path(binding['source'])
    config=read(root/'restore-config.json');case=config['case']
    card,archive=collected(source,case)
    previous,previous_archive=collected(failed,case)
    if (previous!=card or sha(previous_archive)!=sha(archive) or
            inventory(failed/'sealed')!=read(failed/'build.json')['sealed_sha256']):
        raise ValueError('failed launch changed sealed case state')
    receipts=read(receipts_path)
    rows=[row for row in receipts if row.get('case')==case]
    if not rows or len(rows)!=len(receipts) or any(row.get('generation')!=card['sha256'] or row.get('exit')!=1 or
                       row.get('completed_ok') is not False for row in rows):
        raise ValueError('not an unchanged failed-launch reservation')
    evidence={}
    for row in rows:
        launch_id=row['launch_id']
        if not re.fullmatch('[0-9a-f]{32}',launch_id): raise ValueError('invalid launch id')
        state=failed/'control-home/launches'/launch_id
        worker,=(state/'ids').read_text().split()
        cleanup=read(state/'cleanup-status.json')
        if (cleanup!={'primary_exit_code':1,'cleanup_failed':False} or
                not all((state/name).is_file() for name in ('complete',worker+'.collected',worker+'.deleted')) or
                (state/(worker+'.restore-accounting.json')).exists() or
                sha(state/'restore-input-scorecard.json')!=sha(source/'sealed'/(case+'.scorecard.json')) or
                sha(state/'restore-input.tar.gz.age')!=card['sha256']):
            raise ValueError('not a completed pre-restore failure')
        deletion,=failed.glob('results/spend/*/'+worker+'/deletion-completion.json')
        receipt=read(deletion)
        if receipt.get('targetId')!=worker or receipt.get('status')!='completed' or not receipt.get('completedAt'):
            raise ValueError('failed worker disposal not verified')
        for path in (state/'launch.json',state/'cleanup-status.json',deletion):evidence[str(path)]=sha(path)
    save(root/'prior-reservations.json',receipts)
    save(root/'failed-launch-reconciliation.json',dict(failed_bundle=str(failed),
        receipts_source=str(receipts_path),receipts_sha256=sha(receipts_path),generation=card['sha256'],
        unchanged_sealed_sha256=inventory(failed/'sealed'),evidence_sha256=evidence,
        reason='Missing host readiness helper; stopped before restore/accounting/model work; workers collected empty and deleted. New bundle fixes dependency staging; prior failed reservations retained and resolved by explicit policy.'))
    policy=read(root/'policy.restore.pending.json')
    # The pinned holder resolves generations without a time bound. A generation
    # entry would silently clear a later uncertain failure on the same input.
    # Its normal fixed cutoff resolves only these verified historical receipts.
    timestamps=[row.get('at') for row in receipts]
    if any(type(at) not in (int,float) or not math.isfinite(at) or at<=0 or at>=time.time() for at in timestamps):
        raise ValueError('invalid historical receipt timestamp')
    if policy.get('resolved_generations') or policy.get('resolved_before'):
        raise ValueError('reconciliation requires a policy without prior resolution overrides')
    policy['resolved_before']=math.nextafter(max(timestamps),math.inf)
    policy['resolution_explanation']=dict(
        reason=read(root/'failed-launch-reconciliation.json')['reason'],
        generation=card['sha256'],prior_reservations_sha256=sha(root/'prior-reservations.json'),
        reconciliation_sha256=sha(root/'failed-launch-reconciliation.json'))
    save(root/'policy.restore.pending.json',policy)
    for name in ('policy.restore.pending.json', *RECONCILIATION_FILES):
        build['helper_sha256'][name]=sha(root/name)
    save(root/'build.json',build)


def finalize(root):
    if (root/'FINALIZED.json').exists() or (root/'control-home').exists(): raise ValueError('bundle already finalized/launched')
    build=verify_source(root)
    binding=read(root/'source-binding.json');old=Path(binding['source'])
    if sha(old/'policy.restore.json')!=binding['policy_sha256']: raise ValueError('source policy changed')
    config=read(root/'restore-config.json');case=config['case']
    card,archive=collected(old,case)
    launch, = (old/'control-home/launches').glob('*/launch.json')
    if (sha(launch)!=binding['launch_sha256'] or card['sha256']!=binding['generation'] or
            sha(old/'sealed'/(case+'.scorecard.json'))!=binding['public_card_sha256']):
        raise ValueError('collected generation or launch changed after staging')
    if (card['recovery_config']['rounds']!=CASES[case] or card['recovery_config']['case_budget']!=70 or
            card['case_budget']['limit_usd']!=70): raise ValueError('source money/round limits changed')
    from carry_over import usage_facts
    from budget import require_case_budget
    usage_facts(card['continuation_budget']);require_case_budget(card['continuation_budget'],70)
    if card['continuation_budget'].get('active') or card['continuation_budget']['calls']>=CALL_CAP:
        raise ValueError('active or exhausted source accounting')
    proof=retirement(old,case,card,archive)
    save(root/'retirement.json',proof)
    paths=[old/'sealed'/name for name in sorted(collection_files(case)) if (old/'sealed'/name).is_file()]
    before={p.name:sha(p) for p in paths}
    (root/'sealed').mkdir()
    for p in paths: shutil.copy2(p,root/'sealed'/p.name)
    if {p.name:sha(p) for p in paths}!=before or inventory(root/'sealed')!=before:
        raise ValueError('collection changed during finalization')
    checkpoint=root/'sealed'/(case+'.checkpoint.tar.gz.age')
    shutil.copy2(archive,checkpoint)
    import os
    newest=max(p.stat().st_mtime for p in (root/'sealed').iterdir())
    os.utime(checkpoint,(newest+1,newest+1))
    for name in ('input-scorecard.json','expected-restored-scorecard.json'):save(root/name,card)
    save(root/'input-sha256.json',inventory(root/'sealed'))
    save(root/'corrected-continuation-budget.json',card['continuation_budget'])
    for name in FINALIZATION_INPUTS:
        if (old/name).exists():shutil.copy2(old/name,root/name)
    sync=old/'sync-result.json'
    save(root/'vm-current-sha256.json',read(sync)['verified_sha256'] if sync.exists() else read(old/'vm-current-sha256.json'))
    import key_holder
    policy=read(root/'policy.restore.pending.json');policy.update(code_sha256=key_holder.fingerprint(root))
    save(root/'policy.restore.json',policy)
    # Holder ROOT is normally bound at import; validate this new bundle explicitly.
    previous=key_holder.ROOT;key_holder.ROOT=root
    try:
        loaded=key_holder.policy_load(root/'policy.restore.json')
        if key_holder.current_generation(loaded['jobs'][config['job']])!=card['sha256']:raise ValueError('holder generation mismatch')
    finally:key_holder.ROOT=previous
    save(root/'FINALIZED.json',dict(generation=card['sha256'],retirement_sha256=sha(root/'retirement.json'),
        authority=AUTHORITY,decision='D1',max_total_calls=CALL_CAP,case_budget_usd=70,round_limit=CASES[case],
        ttl_hours=16,no_decryption=True,launched=False,prior_ruling_reapplied=False))
    build.update(launch_ready=True,policy_sha256=sha(root/'policy.restore.json'),sealed_sha256=inventory(root/'sealed'))
    save(root/'build.json',build)
    (root/'PREPARATION-BLOCKED.json').unlink()
    verify(root)
    if (root/'prior-reservations.json').exists():
        # A new path must not erase history merely because its socket hash differs.
        runtime=(Path('/private/tmp') if sys.platform=='darwin' else root/'control-home')/(
            'unbug-key-holder-'+str(os.getuid())+'-'+hashlib.sha256(str(root).encode()).hexdigest()[:8])
        key_holder.secure_directory(runtime)
        destination=runtime/'reservations.json'
        if destination.exists() or destination.is_symlink(): raise ValueError('successor reservations already exist')
        save(destination,read(root/'prior-reservations.json'))


def verify(root):
    build=verify_source(root)
    if not build.get('launch_ready') or (root/'PREPARATION-BLOCKED.json').exists():raise ValueError('bundle not finalized')
    if sha(root/'policy.restore.json')!=build['policy_sha256']:raise ValueError('policy changed')
    config=read(root/'restore-config.json');card,_=collected(root,config['case'])
    if (root/'control-home').exists(): return  # outputs may grow after the first launch
    if inventory(root/'sealed')!=build['sealed_sha256']:raise ValueError('finalized input changed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['stage','finalize','verify','reconcile'])
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--collected-from',type=Path)
    parser.add_argument('--release',type=Path)
    parser.add_argument('--adapter',type=Path)
    parser.add_argument('--adapter-sha256')
    parser.add_argument('--rehearsal',type=Path)
    parser.add_argument('--founder-decisions',type=Path,help='D4 exact-release waiver with record digest')
    parser.add_argument('--failed-bundle',type=Path)
    parser.add_argument('--receipts',type=Path)
    a=parser.parse_args()
    if a.command=='stage':
        if not all((a.collected_from,a.release,a.adapter,a.adapter_sha256,a.rehearsal)):parser.error('stage requires source, exact release/adapter and rehearsal evidence')
        stage(a.collected_from.resolve(),a.bundle.resolve(),a.release.resolve(),a.adapter.resolve(),a.adapter_sha256,a.rehearsal.resolve(),
              a.founder_decisions.resolve() if a.founder_decisions else None)
    elif a.command=='reconcile':
        if not a.failed_bundle or not a.receipts: parser.error('reconcile requires failed bundle and retained receipts')
        reconcile_failed_launch(a.bundle.resolve(),a.failed_bundle.resolve(),a.receipts.resolve())
    elif a.command=='finalize':finalize(a.bundle.resolve())
    else:verify(a.bundle.resolve())


if __name__=='__main__':main()
