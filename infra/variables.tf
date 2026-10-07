variable "region" {
  type    = string
  default = "ap-southeast-2"

  validation {
    condition     = var.region == "ap-southeast-2"
    error_message = "Every resource lives in ap-southeast-2."
  }
}
