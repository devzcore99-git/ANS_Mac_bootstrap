{ pkgs, ... }:

# home-manager collapsed the individual git options into one `settings`
# attribute set that mirrors git's own config layout, and moved delta out into
# its own top-level module. Every name below is the replacement the deprecation
# warnings themselves named, so this tracks the same unpinned master the rest of
# the flake does.
{
  programs.git = {
    enable = true;

    # Mirrors gitconfig: each attribute is a config section.
    settings = {
      user = {
        name = "Austin Hill";
        email = "dev.zcore99@gmail.com";
      };

      alias = {
        st = "status";
        co = "checkout";
        br = "branch";
        lg = "log --oneline --graph --decorate";
      };

      init.defaultBranch = "main";
      push.autoSetupRemote = true;
      pull.rebase = true;
      merge.conflictstyle = "zdiff3";
    };
  };

  # Was programs.git.delta. enableGitIntegration used to be implied by enabling
  # delta here; that inference is deprecated, so it is set explicitly.
  programs.delta = {
    enable = true;
    enableGitIntegration = true;
    options = {
      navigate = true;
      side-by-side = true;
    };
  };
}
