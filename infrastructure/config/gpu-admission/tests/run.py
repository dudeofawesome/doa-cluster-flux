"""Check the GPU admission policies against a throwaway local API server.

Starts etcd and kube-apiserver from the Kubernetes envtest binaries, applies
the policies from this repository, then submits every pod in CASES and checks
that it is allowed or denied as its annotations say. Nothing here talks to the
real cluster; the local server lives in a temporary directory and is stopped
when the run ends.

    python3 infrastructure/config/gpu-admission/tests/run.py

The first run downloads the envtest binaries (about 100 MB) into
~/.cache/doa-cluster-flux/envtest and checks their SHA-512. Set
KUBEBUILDER_ASSETS to a directory holding etcd, kube-apiserver and kubectl to
use your own instead.
"""

import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

repo = Path(__file__).resolve().parents[4]

# Match the cluster's minor version, so CEL and admission behave the same.
envtest_version = '1.35.0'
# From https://github.com/kubernetes-sigs/controller-tools/blob/HEAD/envtest-releases.yaml
envtest_sha512 = {
    'darwin-amd64': 'fccc583ba6d322c88a8c56f7876090a7ad63460046a4bcae414093b23ce68a75f172ca7484b7c7475b707657eca5108a8ad3fd85e1b4f70a6c99ca2f22dbd6b2',
    'darwin-arm64': 'bb5d0bb3975956331b0aa0c039955b4c4dc6c5c288e5af369364c7d2fbeac11a025227dabb127569080b259dd29b697cc77fa77abd27ae26721ddb23e8ee0613',
    'linux-amd64': '130369c16f076e724d089189afaede960316f5f5dea6cf57be7a4fc6f09c77342893192509790e4056e116e232dff832ed863f5bd55dcb55d38f3ab834828a11',
    'linux-arm64': 'e53e2b88398f5b9503e3f074d82a2dcb090c708b34940848607ce658138a5d4a25962e042ab683ccc026a8a6c90c0be7f658e42dde0887369d73c3b68e2fc86c',
}

# Applied before the policies: objects the test pods refer to.
setup = [
    repo / 'infrastructure/controllers/nvidia-device-plugin/runtime-class.yaml',
    Path(__file__).parent / 'setup.yaml',
]
# Kustomizations or files holding the policies under test.
policies = [
    repo / 'infrastructure/config/gpu-admission',
]
# Pod fixtures; the header of cases.yaml explains the annotations.
cases = [
    Path(__file__).parent / 'cases.yaml',
]

expect_annotation = 'test.gpu-admission/expect'
describe_annotation = 'test.gpu-admission/describe'


def envtest_assets():
    if os.environ.get('KUBEBUILDER_ASSETS'):
        return Path(os.environ['KUBEBUILDER_ASSETS'])
    system = platform.system().lower()
    machine = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(
        platform.machine(), platform.machine())
    target = f'{system}-{machine}'
    if target not in envtest_sha512:
        sys.exit(f'No pinned envtest build for {target}; set KUBEBUILDER_ASSETS.')
    cache = Path.home() / '.cache/doa-cluster-flux/envtest'
    assets = cache / f'{envtest_version}-{target}'
    if (assets / 'kube-apiserver').exists():
        return assets
    name = f'envtest-v{envtest_version}-{target}.tar.gz'
    url = ('https://github.com/kubernetes-sigs/controller-tools/releases/'
           f'download/envtest-v{envtest_version}/{name}')
    print(f'Downloading {url}')
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / name
    with urllib.request.urlopen(url, timeout=300) as response:
        archive.write_bytes(response.read())
    digest = hashlib.sha512(archive.read_bytes()).hexdigest()
    if digest != envtest_sha512[target]:
        archive.unlink()
        sys.exit(f'SHA-512 mismatch for {name}; refusing to use it.')
    staging = Path(tempfile.mkdtemp(dir=cache))
    with tarfile.open(archive) as tar:
        tar.extractall(staging, filter='data')
    # The archive holds controller-tools/envtest/{etcd,kube-apiserver,kubectl}.
    shutil.move(next(staging.rglob('kube-apiserver')).parent, assets)
    shutil.rmtree(staging)
    archive.unlink()
    return assets


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


class LocalCluster:
    """etcd and kube-apiserver on localhost, with a static admin token."""

    def __init__(self, assets, workdir):
        self.assets = assets
        self.workdir = workdir
        self.processes = []
        self.logs = {}
        self.kubeconfig = workdir / 'kubeconfig'

    def start(self):
        etcd_port, peer_port, api_port = free_port(), free_port(), free_port()
        etcd_url = f'http://127.0.0.1:{etcd_port}'
        peer_url = f'http://127.0.0.1:{peer_port}'
        self.spawn('etcd', [
            self.assets / 'etcd',
            '--data-dir', self.workdir / 'etcd',
            '--listen-client-urls', etcd_url,
            '--advertise-client-urls', etcd_url,
            '--listen-peer-urls', peer_url,
            '--initial-advertise-peer-urls', peer_url,
            '--initial-cluster', f'default={peer_url}',
            '--unsafe-no-fsync',
        ])
        key = self.workdir / 'service-account.key'
        public_key = self.workdir / 'service-account.pub'
        subprocess.run(['openssl', 'genrsa', '-out', key, '2048'],
                       check=True, capture_output=True)
        subprocess.run(['openssl', 'rsa', '-in', key, '-pubout',
                        '-out', public_key], check=True, capture_output=True)
        token = os.urandom(16).hex()
        tokens = self.workdir / 'tokens.csv'
        tokens.write_text(f'{token},admin,admin,"system:masters"\n')
        self.spawn('kube-apiserver', [
            self.assets / 'kube-apiserver',
            '--etcd-servers', etcd_url,
            '--bind-address', '127.0.0.1',
            '--advertise-address', '127.0.0.1',
            '--secure-port', str(api_port),
            '--cert-dir', self.workdir / 'certs',
            '--token-auth-file', tokens,
            '--authorization-mode', 'RBAC',
            '--service-cluster-ip-range', '10.96.0.0/12',
            '--service-account-issuer', 'https://kubernetes.default.svc',
            '--service-account-key-file', public_key,
            '--service-account-signing-key-file', key,
        ])
        self.kubeconfig.write_text(json.dumps({
            'apiVersion': 'v1',
            'kind': 'Config',
            'clusters': [{'name': 'local', 'cluster': {
                'server': f'https://127.0.0.1:{api_port}',
                'insecure-skip-tls-verify': True,
            }}],
            'users': [{'name': 'admin', 'user': {'token': token}}],
            'contexts': [{'name': 'local', 'context': {
                'cluster': 'local', 'user': 'admin'}}],
            'current-context': 'local',
        }))
        deadline = time.monotonic() + 60
        while self.kubectl('get', '--raw', '/readyz').returncode:
            if time.monotonic() > deadline:
                self.fail('kube-apiserver did not become ready')
            time.sleep(0.5)

    def spawn(self, name, args):
        log = open(self.workdir / f'{name}.log', 'w')
        self.logs[name] = log.name
        self.processes.append(subprocess.Popen(
            [str(a) for a in args], stdout=log, stderr=subprocess.STDOUT))

    def stop(self):
        for process in reversed(self.processes):
            process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()

    def fail(self, message):
        for name, path in self.logs.items():
            print(f'--- last lines of {name} log', file=sys.stderr)
            print(''.join(open(path).readlines()[-20:]), file=sys.stderr)
        raise SystemExit(message)

    def kubectl(self, *args, input=None):
        return subprocess.run(
            [self.assets / 'kubectl', '--kubeconfig', self.kubeconfig,
             *map(str, args)],
            input=input, text=True, capture_output=True)

    def must(self, *args, input=None):
        result = self.kubectl(*args, input=input)
        if result.returncode:
            self.fail(f'kubectl {" ".join(map(str, args))} failed:\n'
                      + result.stderr)
        return result.stdout


def manifests(cluster, path):
    """Render a file or kustomization into a list of objects."""
    if path.is_dir():
        rendered = cluster.must('kustomize', path)
    else:
        rendered = path.read_text()
    # kubectl prints one JSON document per object, back to back.
    output = cluster.must('create', '--dry-run=client', '-o', 'json',
                          '-f', '-', input=rendered)
    decoder, objects, index = json.JSONDecoder(), [], 0
    while output[index:].strip():
        index += len(output[index:]) - len(output[index:].lstrip())
        obj, index = decoder.raw_decode(output, index)
        objects.append(obj)
    return objects


def apply(cluster, objects):
    cluster.must('apply', '--server-side', '-f', '-',
                 input=json.dumps({'apiVersion': 'v1', 'kind': 'List',
                                   'items': objects}))


def submit(cluster, pod):
    """Create the pod (dry run) and return the kubectl result.

    A pod with ephemeral containers is first created for real without them, the
    way `kubectl debug` works, and then the containers are added through the
    pods/ephemeralcontainers subresource as a dry run.
    """
    ephemeral = pod['spec'].pop('ephemeralContainers', None)
    if not ephemeral:
        return cluster.kubectl('create', '--dry-run=server', '-f', '-',
                               input=json.dumps(pod))
    created = cluster.kubectl('create', '-o', 'json', '-f', '-',
                              input=json.dumps(pod))
    if created.returncode:
        return created
    created = json.loads(created.stdout)
    created['spec']['ephemeralContainers'] = ephemeral
    meta = created['metadata']
    return cluster.kubectl(
        'replace', '--raw',
        f'/api/v1/namespaces/{meta["namespace"]}/pods/{meta["name"]}'
        '/ephemeralcontainers?dryRun=All',
        '-f', '-', input=json.dumps(created))


def outcome(pod, result):
    """Return None if the result matches the expectation, else a reason."""
    expect = pod['metadata']['annotations'][expect_annotation]
    if expect == 'allow':
        if result.returncode == 0:
            return None
        return 'expected allow, got:\n' + result.stderr.strip()
    if result.returncode == 0:
        return f'expected a denial from {expect}, but it was allowed'
    if f"ValidatingAdmissionPolicy '{expect}'" in result.stderr:
        return None
    return f'expected a denial from {expect}, got:\n' + result.stderr.strip()


def main():
    assets = envtest_assets()
    workdir = Path(tempfile.mkdtemp(prefix='gpu-admission-'))
    cluster = LocalCluster(assets, workdir)
    try:
        cluster.start()
        for path in setup:
            apply(cluster, manifests(cluster, path))
        apply(cluster, [o for path in policies
                        for o in manifests(cluster, path)])

        pods = [o for path in cases for o in manifests(cluster, path)]
        namespaces = sorted({p['metadata'].get('namespace', 'default')
                             for p in pods})
        existing = cluster.must('get', 'namespaces', '-o', 'name').split()
        for namespace in namespaces:
            if f'namespace/{namespace}' not in existing:
                cluster.must('create', 'namespace', namespace)
            # No controller manager runs here to create it.
            cluster.kubectl('create', 'serviceaccount', 'default',
                            '-n', namespace)

        # Policies take a moment to reach the admission plugin; retry the
        #   first denial until it lands. No controller manager runs here, so
        #   policy status (type-checking) is never filled in. A policy that
        #   fails to evaluate is ignored (failurePolicy: Ignore), which the
        #   denial cases catch.
        first_denial = next(
            p for p in pods if 'ephemeralContainers' not in p['spec']
            and p['metadata']['annotations'][expect_annotation] != 'allow')
        deadline = time.monotonic() + 30
        while outcome(first_denial, submit(cluster, json.loads(
                json.dumps(first_denial)))) and time.monotonic() < deadline:
            time.sleep(0.5)

        failures = 0
        for pod in pods:
            meta = pod['metadata']
            label = f'{meta.get("namespace", "default")}/{meta["name"]}'
            reason = outcome(pod, submit(cluster, pod))
            if reason:
                failures += 1
                print(f'FAIL {label}: {meta["annotations"][describe_annotation]}')
                print('     ' + reason.replace('\n', '\n     '))
            else:
                print(f'ok   {label}')
        print(f'\n{len(pods) - failures} passed, {failures} failed')
        return 1 if failures else 0
    finally:
        cluster.stop()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
