import 'reflect-metadata';

import { NestFactory } from '@nestjs/core';

import { AppModule } from './app.module';

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { bufferLogs: false });
  const portEnv = process.env['PORT'];
  const port = portEnv ? Number.parseInt(portEnv, 10) : 3000;
  if (!Number.isFinite(port) || port <= 0) {
    throw new Error(`Invalid PORT: ${portEnv ?? '<unset>'}`);
  }
  await app.listen(port);
}

void bootstrap();
