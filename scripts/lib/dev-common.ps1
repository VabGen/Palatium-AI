# Shared dev-stack process helpers.
# Dot-sourced by scripts/dev-up.ps1 and scripts/dev-down.ps1 — both must agree on what
# counts as "our" process, so the rule lives here instead of twice on disk (050).
#
# Why ownership matters at all: the dev ports overlap with published container ports.
# While the MCP stubs run as containers, Docker Desktop's com.docker.backend.exe listens
# on 8080/8081. "Something listens on our port" therefore does NOT mean the listener is
# ours, and killing the Docker port publisher takes down every published port with it
# (postgres/redis/litellm/neo4j) — recovery needs a Docker Desktop restart. Both callers
# gate on ownership before stopping anything; when in doubt, leave the process alone (020).

#: Entry points this repo launches on the dev ports. A listener whose command line
#: mentions one of these — directly or via an ancestor — is ours; anything else on a dev
#: port belongs to somebody else.
$OurLaunchMarkers = @("palatium_ai.main", "mcp_servers.")

function Get-ProcessTable {
    # One WMI snapshot keyed by pid. The ownership walk needs ancestors, and querying
    # WMI per hop would race the very process tree it is inspecting.
    $table = @{}
    foreach ($proc in Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) {
        $table[[int]$proc.ProcessId] = $proc
    }
    return $table
}

function Get-ProcessOwnerName {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][hashtable]$Table
    )
    if ($Table.ContainsKey($ProcessId)) { return [string]$Table[$ProcessId].Name }
    return "unknown"
}

function Test-OurDevProcess {
    <#
      Whether the listener is one of OUR dev services, not merely something on our port.

      Ours = this process, or a near ancestor, was launched as a repo entry point
      (`python -m palatium_ai.main`, `uvicorn mcp_servers...`). The uvicorn --reload
      worker carries no arguments of its own, hence the walk up the parent chain.

      $Table is shared across ports by the caller so the tree cannot shift between
      checks; omit it for a single check.
    #>
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [hashtable]$Table,
        [int]$MaxDepth = 6
    )

    if (-not $Table) { $Table = Get-ProcessTable }

    $current = $ProcessId
    for ($depth = 0; $depth -lt $MaxDepth; $depth++) {
        if (-not $Table.ContainsKey($current)) { return $false }
        $proc = $Table[$current]
        foreach ($marker in $OurLaunchMarkers) {
            if ([string]$proc.CommandLine -like "*$marker*") { return $true }
        }
        $parent = [int]$proc.ParentProcessId
        if ($parent -le 0 -or $parent -eq $current) { return $false }
        $current = $parent
    }
    return $false
}
