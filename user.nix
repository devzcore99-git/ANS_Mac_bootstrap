# Machine identity consumed by flake.nix.
#
# MUST be committed to git. Nix flakes in a git repository only see
# git-tracked files, so an untracked or gitignored user.nix is invisible
# to evaluation even when it exists on disk.
#
# hostname keys darwinConfigurations.<hostname> and is applied to the machine.
# bootstrap.sh and the `rebuild` helper both select it explicitly, so it need
# not match `scutil --get LocalHostName` up front — but a bare
# `darwin-rebuild switch --flake <path>` defaults to the live hostname and
# fails until the two agree.
#
# flakeDir is the absolute path to this clone, used as the fallback target of
# the `rebuild` helper when it is run from outside the repo. Leave it null to
# rely on runtime resolution (cwd, or $FLAKE_DIR) — see home/zsh.nix. Set it
# only if you want `rebuild` to work from anywhere, and keep it accurate: a
# stale path here is worse than none.
{
  username = "ahill";
  hostname = "Austins-MacBook-Air";
  flakeDir = null;
}
