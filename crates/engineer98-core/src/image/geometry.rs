/// Cylinder-Head-Sector address, as used by the PC-98 IPL1 partition table.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CHS {
    pub cylinder: u16,
    pub head: u8,
    pub sector: u8,
}

/// Disk geometry. PC-98 uses C/H/S throughout, so LBA is derived, never stored.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Geometry {
    pub cylinders: u32,
    pub heads: u32,
    pub sectors_per_track: u32,
    pub sector_size: u32,
}

impl Geometry {
    /// Total addressable sectors.
    pub fn total_sectors(&self) -> u32 {
        self.cylinders * self.heads * self.sectors_per_track
    }

    /// Total bytes of addressable data (excluding any header).
    pub fn total_bytes(&self) -> u64 {
        self.total_sectors() as u64 * self.sector_size as u64
    }

    /// Convert CHS to a linear sector index. Sectors are 1-based on PC-98.
    pub fn chs_to_lba(&self, chs: CHS) -> Option<u32> {
        if chs.sector == 0 || chs.sector as u32 > self.sectors_per_track {
            return None;
        }
        let lba = (chs.cylinder as u32 * self.heads + chs.head as u32)
            * self.sectors_per_track
            + (chs.sector as u32 - 1);
        (lba < self.total_sectors()).then_some(lba)
    }
}