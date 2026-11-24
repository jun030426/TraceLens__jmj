// Existing lectures with individually approved covers.
const posters: Readonly<Record<string, string>> = {
  "11ba3be9-1e94-4112-8d38-77b2d2f1dca0": "/lecture-posters/len-warm-6b47d698b62f.webp",
  "0624e145-7a5b-4194-848a-c3ce45f3c221": "/lecture-posters/upper-warm-dea3700a6a74.webp",
  "82ee6a44-5e25-4599-9f8d-4975e1bacd28": "/lecture-posters/lower-warm-f097f30d9357.webp"
};

export function conceptVideoPoster(videoId: string, generatedPoster?: string | null): string {
  return generatedPoster || posters[videoId] || "/lecture-posters/default-lecture.webp";
}
