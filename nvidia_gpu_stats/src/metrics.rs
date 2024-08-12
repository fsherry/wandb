use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Serialize)]
pub struct Metrics {
    #[serde(flatten)]
    metrics: BTreeMap<String, serde_json::Value>,
}

impl Metrics {
    pub fn new() -> Self {
        Metrics {
            metrics: BTreeMap::new(),
        }
    }

    pub fn add_metric<T: Into<serde_json::Value>>(&mut self, key: &str, value: T) {
        self.metrics.insert(key.to_string(), value.into());
    }

    pub fn add_timestamp(&mut self, timestamp: f64) {
        self.add_metric("_timestamp", timestamp);
    }

    pub fn print_json(&self) -> Result<(), serde_json::Error> {
        let json_output = serde_json::to_string(&self.metrics)?;
        println!("{}", json_output);
        Ok(())
    }
}
