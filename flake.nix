{
  description = "Nix flakes";

  inputs = {
    nixpkgs.url = "nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [ pkgs.zlib pkgs.libgcc.lib sqlite.dev python310 poetry inkscape zoteo ];

          LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
            pkgs.libgcc.lib pkgs.zlib
          ];

          shellHook = ''
            source ./.venv/bin/activate
          '';
        };
      });
}
