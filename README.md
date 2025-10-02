# Simple Web App

## Development Guidelines

We use `uv2nix` to build a python package and a virtual environment with all its dependencies.
Everything in the `src/` folder should get included in the built Python package.
The entire web app logic should be contained within the Python package and consequently in the `src/` folder.

Configuration, on the other hand, should, whenever possible, be kept outside of the Python package.
Keep the application itself configuration-agnostic whenever possible and choose to instead maintain the `.env.example` file containing a suggested default configuration for developers.
Configuration should thus always be performed via environment variables.
In this way and some others, we follow the principles of the [12-factor app](https://12factor.net/).

## Developer Setup

Since configuration is all performed via environment variables and everything else is stored in the package, all you need to do to get started is:
1. Run `cp .env.example .env`: Copy the example environment file. Since we're not really using any secrets, the default configuration should suffice for now.
2. Load environment variables from the `.env` file. I have a function `loadenv` which does this for me. Lots of people do this automatically with [direnv](https://direnv.net/), and VS Code's Python extension does this automatically too.
3. Run `uv sync` or `nix develop .#impure` followed by `uv sync` or `nix develop .#uv2nix`: Create a virtual environment and install the required dependencies.
4. Run either `uv run simple-web-app` (if you used `uv sync` above) or `simple-web-app` (if you used the `.#uv2nix approach`: Run the server locally. The application should automatically create a database file (based on the value of `DATABASE_PATH` from your `.env` file) and apply the necessary migrations to it. By default, `uvicorn` will reload the web server whenever files in the `src/` folder change.
5. Go to [localhost:8000](http://localhost:8000/) (assuming you didn't override the `UVICORN_PORT` variable in the `.env` file) to see the page.

