{
  description = "GauseDrone splat pipeline and app: capture -> COLMAP -> gsplat -> web viewer";

  # Pinned to the same nixpkgs revision as the host NixOS system so most
  # paths are already in the store or on cache.nixos.org.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/4975466d324710c576dc11ad614684e6bd8cad8e";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      lib = nixpkgs.lib;
      pkgs = import nixpkgs {
        inherit system;
        # Only the NVIDIA CUDA redistributables are unfree.
        config.allowUnfreePredicate = pkg:
          lib.hasPrefix "cuda" (lib.getName pkg) || lib.hasPrefix "libcu" (lib.getName pkg);
      };

      python = pkgs.python312;
      cuda = pkgs.cudaPackages; # 12.9, matches the torch cu129 wheels in pyproject.toml

      # torch.utils.cpp_extension (used by gsplat to JIT-compile its CUDA
      # kernels) expects a single CUDA_HOME with bin/, include/ and lib64/.
      cudaHome = pkgs.symlinkJoin {
        name = "cuda-home-${cuda.cudaMajorMinorVersion}";
        paths = lib.concatMap (p: map (o: p.${o}) p.outputs) (with cuda; [
          cuda_nvcc
          cuda_cudart
          cccl
        ]);
        postBuild = "ln -s $out/lib $out/lib64";
      };

      # nvcc 12.9 rejects the newest GCC; use the host compiler nixpkgs pairs with it.
      hostCC = cuda.backendStdenv.cc;

      # CUDA COLMAP (GPU SIFT extraction + matching). cache.nixos.org has no
      # CUDA builds, so the first `nix develop` compiles it locally (once per
      # nixpkgs bump). Kernels only for the RTX 40xx (sm_89) to keep that short;
      # add capabilities here for other GPUs.
      colmap = pkgs.colmap.override {
        cudaSupport = true;
        cudaPackages = cuda;
        cudaCapabilities = [ "8.9" ];
        enableTests = false;
      };
    in
    {
      devShells.${system}.default = pkgs.mkShell {
        packages = [
          python
          pkgs.uv
          pkgs.nodejs_22
          colmap
          pkgs.ffmpeg
          pkgs.ninja
          pkgs.git
          cudaHome
          hostCC
        ];

        shellHook = ''
          # Works from this directory or from the repo root (`nix develop ./gaussian-scanning`).
          export PROJECT_ROOT="$PWD"
          [ -f "$PROJECT_ROOT/pyproject.toml" ] || export PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)/gaussian-scanning"

          # Python deps (torch, gsplat, fastapi...) live in a uv-managed venv
          # locked by uv.lock. Never let uv download its own interpreter:
          # generic Linux binaries don't run on NixOS.
          export UV_PYTHON="${python}/bin/python3.12"
          export UV_PYTHON_DOWNLOADS=never
          export UV_PROJECT_ENVIRONMENT="$PROJECT_ROOT/.venv"

          export CUDA_HOME="${cudaHome}"
          export CC="${hostCC}/bin/cc"
          export CXX="${hostCC}/bin/c++"

          # pip wheels need libstdc++/zlib; torch needs the driver's libcuda.
          # On non-NixOS hosts the driver lives elsewhere; fall back to ldconfig.
          DRIVER_LIB=/run/opengl-driver/lib
          if [ ! -e "$DRIVER_LIB/libcuda.so.1" ]; then
            DRIVER_LIB="$(dirname "$(/sbin/ldconfig -p 2>/dev/null | awk '/libcuda.so.1/{print $NF; exit}')" 2>/dev/null)"
          fi
          export LD_LIBRARY_PATH="$DRIVER_LIB:${lib.makeLibraryPath [ pkgs.stdenv.cc.cc.lib pkgs.zlib ]}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

          export PYTHONPATH="$PROJECT_ROOT''${PYTHONPATH:+:$PYTHONPATH}"
          export PATH="$PROJECT_ROOT/bin:$PATH"

          if [ -f "$PROJECT_ROOT/uv.lock" ]; then
            uv sync --frozen --quiet --project "$PROJECT_ROOT" && . "$PROJECT_ROOT/.venv/bin/activate"
          fi
          # pip's `ninja` wheel (a gsplat dependency) ships a generic-Linux
          # binary that NixOS can't exec; make sure the Nix one wins.
          export PATH="${pkgs.ninja}/bin:$PATH"
        '';
      };
    };
}
