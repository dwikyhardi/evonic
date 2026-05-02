import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
  site: 'https://evonic.dev',
  integrations: [
    starlight({
      title: 'Evonic',
      description: 'Documentation for the Evonic platform — open-source AI agent orchestration.',
      logo: {
        src: './src/assets/evonic-logo.svg',
        replacesTitle: true,
      },
      social: {
        github: 'https://github.com/anvie/evonic',
      },
      sidebar: [
        {
          label: 'Mulai',
          slug: 'getting-started',
        },
        {
          label: 'CLI Reference',
          autogenerate: { directory: 'cli' },
        },
        {
          label: 'Panduan',
          autogenerate: { directory: 'guide' },
        },
      ],
      locales: {
        root: {
          label: 'Bahasa Indonesia',
          lang: 'id',
        },
      },
      defaultLocale: 'root',
    }),
  ],
});
