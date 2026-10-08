/**
 * SCRUM-31 only enforces one architectural rule: files under src/core/ are
 * the pure functional core (no I/O) and must not import from src/infra/.
 * SCRUM-34 adds the broader lint toolchain (@typescript-eslint rules,
 * Prisma-specific checks, formatting).
 */
module.exports = {
  root: true,
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 2022,
    sourceType: 'module',
  },
  env: {
    node: true,
    es2022: true,
  },
  ignorePatterns: ['dist/', 'node_modules/', 'coverage/'],
  rules: {},
  overrides: [
    {
      files: ['src/core/**/*.ts'],
      rules: {
        'no-restricted-imports': [
          'error',
          {
            patterns: [
              {
                group: ['**/infra', '**/infra/**'],
                message:
                  'src/core/ must stay I/O-free. Pass values and callbacks in; do not import from src/infra/.',
              },
            ],
          },
        ],
      },
    },
  ],
};
