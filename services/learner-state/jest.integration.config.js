/**
 * Integration tests run against real Postgres via Testcontainers
 * (architecture App. C.4). Docker must be running.
 */
module.exports = {
  rootDir: '.',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/test/integration/**/*.spec.ts'],
  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.spec.json' }],
  },
  // First run pulls the Postgres image.
  testTimeout: 180_000,
};
