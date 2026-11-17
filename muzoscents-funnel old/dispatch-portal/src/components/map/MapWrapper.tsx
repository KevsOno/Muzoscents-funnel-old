import { LeafletMap } from './LeafletMap';
import type { MapWrapperProps } from './types';

/**
 * Provider-agnostic map. Today renders Leaflet/OSM.
 * To swap to Google Maps later: replace the body of this component and
 * nothing else in the codebase needs to change.
 */
export function MapWrapper(props: MapWrapperProps) {
  return <LeafletMap {...props} />;
}
