"use client";

import dynamic from "next/dynamic";

export type TbbmMapItem = {
  id: string;
  tbbm_code: string;
  name: string;
  terminal_type: string;
  province_name?: string | null;
  address?: string | null;
  verification_status: string;
  latitude: number;
  longitude: number;
};

export type TbbmMapProps = {
  terminals: TbbmMapItem[];
  heightClass?: string;
  selectedId?: string | null;
  onSelect?: (terminal: TbbmMapItem) => void;
};

const TbbmMapInner = dynamic(() => import("./TbbmMapInner"), {
  ssr: false,
  loading: () => <div className="skeleton h-full min-h-72 w-full" />,
});

export default function TbbmMap(props: TbbmMapProps) {
  return <TbbmMapInner {...props} />;
}
