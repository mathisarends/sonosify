from sonosify.cli._dependencies import Console

console = Console()
error_console = Console(stderr=True, style="bold red")
