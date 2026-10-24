import { useEffect, useRef } from 'react';
import OpenSeadragon from 'openseadragon';

export type ViewerTileSource = string | { type: 'image'; url: string };

export function OpenSeadragonViewer({
  tileSources,
  sourceKey,
  onReady,
  onTileLoaded,
  onError,
  label,
}: {
  tileSources: ViewerTileSource;
  sourceKey: string;
  onReady: (viewer: OpenSeadragon.Viewer) => void;
  onTileLoaded?: () => void;
  onError: (message: string) => void;
  label: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const readyRef = useRef(onReady);
  const tileLoadedRef = useRef(onTileLoaded);
  const errorRef = useRef(onError);
  useEffect(() => {
    readyRef.current = onReady;
    tileLoadedRef.current = onTileLoaded;
    errorRef.current = onError;
  });

  useEffect(() => {
    if (!containerRef.current) return;
    let destroyed = false;
    let firstTileSeen = false;
    const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const viewer = OpenSeadragon({
      element: containerRef.current,
      showNavigationControl: false,
      showZoomControl: false,
      showHomeControl: false,
      showFullPageControl: false,
      showNavigator: false,
      showSequenceControl: false,
      showRotationControl: false,
      gestureSettingsMouse: {
        clickToZoom: false,
        dblClickToZoom: true,
        flickEnabled: true,
      },
      drawer: 'canvas',
      visibilityRatio: 0.55,
      constrainDuringPan: true,
      minZoomImageRatio: 0.5,
      maxZoomPixelRatio: 6,
      animationTime: reducedMotion ? 0 : 0.45,
      springStiffness: 9,
      immediateRender: false,
      imageLoaderLimit: 4,
    });
    const singleImage = typeof tileSources === 'object' && tileSources.type === 'image';
    viewer.addHandler('open', () => {
      if (destroyed) return;
      readyRef.current(viewer);
      // OpenSeadragon's single-image source does not always emit tile-loaded.
      if (singleImage && !firstTileSeen) {
        firstTileSeen = true;
        tileLoadedRef.current?.();
      }
    });
    viewer.addHandler('tile-loaded', () => {
      if (destroyed || firstTileSeen) return;
      firstTileSeen = true;
      tileLoadedRef.current?.();
    });
    viewer.addHandler('open-failed', (event) => {
      if (destroyed) return;
      const message =
        typeof event?.message === 'string'
          ? event.message
          : 'The IIIF image service could not be opened.';
      errorRef.current(message);
    });
    try {
      viewer.open(tileSources as unknown as OpenSeadragon.TileSourceSpecifier);
    } catch (error) {
      errorRef.current(error instanceof Error ? error.message : 'The image could not be opened.');
    }
    return () => {
      destroyed = true;
      viewer.destroy();
    };
    // tileSources is encoded by sourceKey; callbacks are held in refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKey]);

  return <div ref={containerRef} className="osd-viewer" role="img" aria-label={label} />;
}
