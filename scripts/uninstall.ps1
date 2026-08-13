[CmdletBinding()]
param()

Set-StrictMode -Version Latest
[Console]::Error.WriteLine('Repository-invoked uninstall is no longer supported. Run the installed dev-flow-uninstall command; it requires neither Git nor a source checkout.')
exit 2
