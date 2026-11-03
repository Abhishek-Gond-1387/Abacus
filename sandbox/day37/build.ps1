$ErrorActionPreference = 'Stop'

$baseTag = 'python:3.13-slim-bookworm'
$imageTag = 'abacus-sandbox-day37:local'
$contextPath = Join-Path $PSScriptRoot 'image'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker CLI is unavailable. Install an eligible Linux-container runtime, then rerun this script.'
}

$server = docker version --format '{{.Server.Os}}|{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $server) {
    throw 'Docker Engine is unavailable. Start Docker Desktop and select its Linux-container backend.'
}
$serverParts = $server.Trim() -split '\|', 2
if ($serverParts.Count -ne 2 -or $serverParts[0] -ne 'linux') {
    throw "Expected a Linux Docker engine; received '$server'. No image was built."
}

docker pull $baseTag
if ($LASTEXITCODE -ne 0) { throw "Could not pull the official base image '$baseTag'." }

$baseDigest = docker image inspect --format '{{index .RepoDigests 0}}' $baseTag
if ($LASTEXITCODE -ne 0 -or $baseDigest -notmatch '^python@sha256:[0-9a-f]{64}$') {
    throw 'Could not resolve the pulled official Python image to an immutable repository digest.'
}

docker build --network=none --pull=false --build-arg "PYTHON_BASE=$baseDigest" --tag $imageTag $contextPath
if ($LASTEXITCODE -ne 0) { throw 'The offline, digest-pinned probe image build failed.' }

$image = docker image inspect --format '{{.Id}}|{{index .Config.Labels "org.abacus.base-image"}}' $imageTag
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the built probe image.' }
Write-Output "Built $imageTag from $image"
Write-Output "Next: python sandbox/day37/verify.py --image $imageTag"
