# Simple Web App

We use `uv2nix` to build a python package and a virtual environment with all its dependencies.
Everything in the `src/` folder should get included in the built Python package.
The entire web app logic should be contained within the Python package and consequently in the `src/` folder.

Configuration, on the other hand, should, whenever possible, be kept outside of the Python package.
Keep the application itself configuration-agnostic whenever possible and choose to instead maintain the `.env.example` file containing a suggested default configuration for developers.
Configuration should thus always be performed via environment variables.

## Todo
- ~~Use OOB for loading more articles~~
- Look into Jinja macros for components
- ~~Fix tabs~~
- Fix paths and full page loads 

