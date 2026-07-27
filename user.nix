# Machine identity consumed by flake.nix.
#
# MUST be committed to git. Nix flakes in a git repository only see
# git-tracked files, so an untracked or gitignored user.nix is invisible
# to evaluation even when it exists on disk.
#
# hostname must match `scutil --get LocalHostName`, since darwin-rebuild
# selects darwinConfigurations.<hostname> by default.
{
  username = "ahill";
  hostname = "Austins-MacBook-Air";
}
