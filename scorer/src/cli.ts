#!/usr/bin/env node

/**
 * CLI entry point for the scorer
 * Reads JSON from stdin, outputs results to stdout
 */

import { stdin, stdout, stderr } from 'process';
import { scoreVideo } from './scorer.js';

async function main(): Promise<void> {
  let inputData = '';

  // Read JSON from stdin
  for await (const chunk of stdin) {
    inputData += chunk;
  }

  try {
    // Parse input
    const input = JSON.parse(inputData);

    // Score the video
    const result = scoreVideo(input);

    // Output result as JSON
    stdout.write(JSON.stringify(result, null, 2));
    stdout.write('\n');

    process.exit(0);
  } catch (error) {
    // Output error as JSON to stderr
    const errorOutput = {
      error: error instanceof Error ? error.message : 'Unknown error',
      stack: error instanceof Error ? error.stack : undefined,
      type: error instanceof Error ? error.constructor.name : 'UnknownError',
    };

    stderr.write(JSON.stringify(errorOutput, null, 2));
    stderr.write('\n');

    process.exit(1);
  }
}

main();
