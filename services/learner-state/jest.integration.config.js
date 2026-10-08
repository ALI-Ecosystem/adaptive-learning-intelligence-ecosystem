/**
 * Integration tests run against real Postgres via Testcontainers
 * (architecture App. C.4). Docker must be running.
 */
module.exports = {
  rootDir: '.',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/test/integration/**/*.spec.ts'],
  // One Postgres for the whole run, shared by every suite.
  globalSetup: '<rootDir>/test/integration/support/global-setup.ts',
  globalTeardown: '<rootDir>/test/integration/support/global-teardown.ts',
  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.spec.json' }],
  },
  testTimeout: 30_000,
};
