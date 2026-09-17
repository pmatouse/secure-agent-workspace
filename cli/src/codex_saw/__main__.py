"""Entry point for codex-saw TUI and CLI subcommands."""

import sys


def main():
    args = sys.argv[1:]

    if args and args[0] == "shell" and len(args) >= 2:
        from .ssh import shell
        shell(args[1])
    elif args and args[0] == "ssh-proxy" and len(args) >= 2:
        from .ssh import ssh_proxy
        kwargs = {}
        if "--expected-session-uid" in args:
            idx = args.index("--expected-session-uid")
            kwargs["expected_uid"] = args[idx + 1]
        if "--non-interactive" in args:
            kwargs["non_interactive"] = True
        ssh_proxy(args[1], **kwargs)
    elif args and args[0] == "ssh-config" and len(args) >= 2:
        from .ssh import generate_ssh_config
        print(generate_ssh_config(args[1]))
    elif args and args[0] == "desktop":
        from . import desktop
        if len(args) >= 3 and args[1] == "register":
            desktop.register(args[2])
        elif len(args) >= 3 and args[1] == "doctor":
            desktop.doctor(args[2])
        elif len(args) >= 3 and args[1] == "unregister":
            desktop.unregister(args[2])
        else:
            print("Usage: codex-saw desktop <register|doctor|unregister> <session>")
            sys.exit(1)
    else:
        from .app import CodexSawApp
        app = CodexSawApp()
        app.run()


if __name__ == "__main__":
    main()
