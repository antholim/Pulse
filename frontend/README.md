## Node.js version

PULSE uses Node.js 22 for frontend development.

We recommend using `nvm` to manage Node.js versions.

From the repository root:

```bash
nvm install
nvm use
```

Then install frontend dependencies:

```bash
cd frontend
npm ci
npm run dev
```

The required Node.js major version is documented in the root `.nvmrc` file. Developers should use a compatible npm version and commit changes to `package-lock.json` when dependencies are intentionally updated.
