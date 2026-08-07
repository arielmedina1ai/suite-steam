[CmdletBinding()]
param([switch]$Repair,[switch]$Quiet)
$ErrorActionPreference = 'Stop'
$ModuleName = 'SharePointPnPPowerShellOnline'
$DependencyDll = 'Microsoft.IdentityModel.Clients.ActiveDirectory.dll'
$started = Get-Date
$records = @()
function Emit([string]$status,[string]$message) { [ordered]@{status=$status;module=$ModuleName;dependency=$DependencyDll;versions=@($records);message=$message;duration_ms=[int]((Get-Date)-$started).TotalMilliseconds} | ConvertTo-Json -Compress -Depth 6 }
function Check {
 if ($env:OS -ne 'Windows_NT') { return @{status='UNSUPPORTED_ENVIRONMENT';message='O sistema não é Windows.'} }
 foreach ($command in @('Get-Module','Install-Module','Uninstall-Module')) { if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { return @{status='UNSUPPORTED_ENVIRONMENT';message="$command não está disponível."} } }
 $found=@(Get-Module -ListAvailable -Name $ModuleName | Sort-Object Version -Descending)
 if (!$found.Count) { return @{status='MODULE_NOT_FOUND';message='Módulo obrigatório não encontrado.'} }
 $missing=$false;$inaccessible=$false;$invalid=$false;$records=@()
 foreach($item in $found) { $dir=Split-Path -Parent $item.Path;$dll=Join-Path $dir $DependencyDll;$exists=Test-Path -LiteralPath $dll -PathType Leaf;$readable=$false;if($exists){try{$s=[IO.File]::OpenRead($dll);$s.Dispose();$readable=$true}catch{$inaccessible=$true}};if(!(Test-Path -LiteralPath $dir -PathType Container)){$invalid=$true};if(!$exists){$missing=$true};$records += [ordered]@{version=[string]$item.Version;path=$dir;dependency_path=$dll;dependency_exists=$exists;dependency_readable=$readable} }
 try { Import-Module $ModuleName -Force -ErrorAction Stop } catch { $text=$_.Exception.Message;$status='IMPORT_FAILED';if($text -match 'already loaded|carregado'){$status='ASSEMBLY_CONFLICT'}elseif($text -match 'denied|permiss'){$status='PERMISSION_DENIED'};return @{status=$status;message=$text} }
 if($invalid){return @{status='MODULE_PATH_INVALID';message='Caminho de módulo inválido.'}};if($inaccessible){return @{status='DEPENDENCY_INACCESSIBLE';message='A DLL não pôde ser lida.'}};if($missing){return @{status='DEPENDENCY_MISSING';message='A DLL principal não foi encontrada.'}};if($found.Count -gt 1){return @{status='MULTIPLE_VERSIONS';message='Múltiplas versões instaladas.'}};return @{status='OK';message='Dependências validadas com sucesso.'}
}
try { $r=Check;if(!$Repair){Emit $r.status $r.message;exit 0};if($r.status -eq 'OK'){Emit 'OK' 'Nenhum reparo necessário.';exit 0};try{Remove-Module $ModuleName -Force -ErrorAction SilentlyContinue}catch{};Uninstall-Module $ModuleName -AllVersions -Force -ErrorAction Stop;Install-Module $ModuleName -Force -AllowClobber -Scope CurrentUser -ErrorAction Stop;$records=@();$v=Check;if($v.status -eq 'OK'){Emit 'REPAIRED_OK' 'Módulo reinstalado e validado.';exit 0};Emit 'VALIDATION_FAILED' $v.message;exit 1 } catch { $s='REPAIR_FAILED';if($_.Exception.Message -match 'denied|permiss'){$s='PERMISSION_DENIED'};Emit $s $_.Exception.Message;exit 1 }