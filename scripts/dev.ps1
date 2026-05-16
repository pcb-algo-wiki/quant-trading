# 开发常用任务入口（Windows PowerShell）
# 用法: pwsh scripts/dev.ps1 <install|test|test-cov|lint|pipeline|pipeline-dry>
param(
    [Parameter(Position=0)]
    [ValidateSet('install','test','test-cov','lint','pipeline','help')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

switch ($Task) {
    'install' {
        python -m pip install --upgrade pip
        python -m pip install -r requirements.txt
    }
    'test' {
        python -m pytest -q
    }
    'test-cov' {
        python -m pytest --cov=. --cov-report=term-missing
    }
    'lint' {
        # 项目暂未启用统一 linter，先跑 py_compile 兜底语法检查
        Get-ChildItem -Recurse -Filter *.py -Path data,strategies,backtest,execution,knowledge,research,ml,data_store,utils,scripts |
            ForEach-Object { python -m py_compile $_.FullName }
        Write-Host 'py_compile OK'
    }
    'pipeline' {
        python run.py --daily-pipeline
    }
    default {
        Write-Host "Tasks: install | test | test-cov | lint | pipeline"
    }
}
