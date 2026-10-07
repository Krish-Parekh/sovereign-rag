variable "region" {
  type    = string
  default = "ap-southeast-2"

  validation {
    condition     = var.region == "ap-southeast-2"
    error_message = "Every resource lives in ap-southeast-2."
  }
}

variable "chat_model" {
  type    = string
  default = "qwen.qwen3-32b-v1:0"
}

variable "alert_email" {
  type        = string
  description = "Address that receives alarm emails. Confirm the subscription from the inbox."
}

variable "mfa_configuration" {
  type        = string
  default     = "ON"
  description = "Cognito MFA. ON (TOTP required) is the design. OFF is for short tests only."

  validation {
    condition     = contains(["ON", "OFF"], var.mfa_configuration)
    error_message = "Use ON or OFF."
  }
}
