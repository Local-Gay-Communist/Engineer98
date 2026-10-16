use super::error::{ImageError, Result};
use super::geometry::Geometry;
use super::partition::Partition;
use super::DiskImage;

const D88_HEADER_SIZE: usize = 0x2B0;
const D88_MAX_TRACKS: usize = 164;

/// One sector extracted from the D88 track/sector structure.
struct SectorRecord {
    cylinder: u8,
    head: u8,
    sector: u8,
    data: Vec<u8>,
}

pub struct D88Image {
    data: Vec<u8>,
    sectors: Vec<SectorRecord>,
    geom: Geometry,
}

impl D88Image {
    pub fn from_bytes(data: Vec<u8>) -> Result<Self> {
        if data.len() < D88_HEADER_SIZE {
            return Err(ImageError::Truncated {
                expected: D88_HEADER_SIZE,
                actual: data.len(),
            });
        }

        let mut sectors = Vec::new();
        let mut max_cyl = 0u32;
        let mut max_head = 0u32;
        let mut max_sector = 0u32;
        let mut sector_size = 0u32;

        for t in 0..D88_MAX_TRACKS {
            let off = 0x20 + t * 4;
            let track_off = read_u32(&data, off) as usize;
            if track_off == 0 {
                continue;
            }
            if track_off + 16 > data.len() {
                continue;
            }
            let sector_count = u16::from_le_bytes([data[track_off], data[track_off + 1]]) as usize;
            let mut pos = track_off + 16;
            for _ in 0..sector_count {
                if pos + 16 > data.len() {
                    break;
                }
                let cylinder = data[pos];
                let head = data[pos + 1];
                let sector = data[pos + 2];
                let size_shift = data[pos + 3];
                let data_size = 128usize << size_shift;
                let data_start = pos + 16;
                let data_end = data_start + data_size;
                if data_end > data.len() {
                    break;
                }
                max_cyl = max_cyl.max(cylinder as u32);
                max_head = max_head.max(head as u32);
                max_sector = max_sector.max(sector as u32);
                sector_size = data_size as u32;
                sectors.push(SectorRecord {
                    cylinder,
                    head,
                    sector,
                    data: data[data_start..data_end].to_vec(),
                });
                pos = data_end;
            }
        }

        if sectors.is_empty() {
            return Err(ImageError::Unsupported("D88 with no readable sectors"));
        }

        Ok(Self {
            data,
            sectors,
            geom: Geometry {
                cylinders: max_cyl + 1,
                heads: max_head + 1,
                sectors_per_track: max_sector,
                sector_size,
            },
        })
    }
}

impl DiskImage for D88Image {
    fn geometry(&self) -> Geometry {
        self.geom
    }

    fn read_sector(&self, lba: u32) -> Result<Vec<u8>> {
        // Convert LBA to CHS using the derived geometry, then find the record.
        let spt = self.geom.sectors_per_track;
        let heads = self.geom.heads;
        let cylinder = (lba / (heads * spt)) as u8;
        let head = ((lba / spt) % heads) as u8;
        let sector = (lba % spt) as u8 + 1;

        for rec in &self.sectors {
            if rec.cylinder == cylinder && rec.head == head && rec.sector == sector {
                return Ok(rec.data.clone());
            }
        }
        Err(ImageError::OutOfRange {
            lba,
            max: self.geom.total_sectors().saturating_sub(1),
        })
    }

    fn partitions(&self) -> Result<Vec<Partition>> {
        Ok(Vec::new())
    }

    fn format_name(&self) -> &'static str {
        "D88"
    }
}

fn read_u32(data: &[u8], off: usize) -> u32 {
    u32::from_le_bytes([
        data[off], data[off + 1], data[off + 2], data[off + 3],
    ])
}