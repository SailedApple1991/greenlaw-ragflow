# Wkst 8 - PFCs Emissions

Primary Aluminum Production
Worksheet 8: PFC Emissions -  Slope or Overvoltage Method
 | IPPC Tier 3 method : if direct measurements of CF4 and C2F6  have been made at smelters, potline or smelter specific correlations between PFC emissions and anode effect operating parameters (AEM or AEO) can be developed
 | IPPC Tier 2 method : if no direct measurements of CF4 and C2F6  have been made at smelters, average industry coefficients depending on the cells technologies are to be used by default
 | Two PFC calculation methods and equations are proposed to calculate emission factors (kg PFC / t Al) according to anode effect process parameters available
 | They apply to both Tier 2 and Tier 3 IPPC methods
Slope Method (IPCC Tier 2 or Tier 3 method)
Equation 1:
 |  |  | RCF4 (kg CF4 / t Al) = AEM x SCF4 |  |  | WITH |  | SCF4 = Slope Coefficients (Tier 2 or Tier 3 based on facility measurements)
 |  |  | RC2F6 (kg C2F6 / t Al) = RCF4 x FC2F6/CF4 |  |  |  |  | AEM = anode effect minutes per cell day
 |  |  |  |  |  |  |  | FC2F6/CF4 = weight fraction C2F6/CF4
Overvoltage Method (IPCC Tier 2 or Tier 3 method)
Equation 2:
 |  |  | RCF4 (kg CF4 / t Al) = (AEO/CE) x OVC |  |  | WITH |  | OVC = Overvoltage Coefficients (Tier 2 or Tier 3 based on facility measurements)
 |  |  | RC2F6 (kg C2F6 / t Al) = RCF4 x FC2F6/CF4 |  |  |  |  | AEO = anode effect overvoltage in millivolts per cell
 |  |  |  |  |  |  |  | CE = current efficiency for aluminium production in percent
 |  |  |  |  |  |  |  | FC2F6/CF4 = weight fraction C2F6/CF4
 |  |  | Cell colour code:
 |  |  | Example using default factors
 |  |  | User entry:
 |  |  | Optional user entry:
 |  |  | Auto calculated value:
 | Equation 1 - Anode Effect Minutes Per Cell Day (Slope Method)
 |  |  | A |  | B |  |  | C |  | D | E |  | F | G |  | Tier 2 Factors
 |  |  | Type of cell | Weight of aluminium produced | Process Anode Effect parameters |  |  | Tier 3 site specific CF4 Slope Coefficients | Used CF4 Slope Coefficients | CF4 Emissions | Tier 3 site specific Weight Fraction C2F6/CF4 | Used Weight Fraction C2F6/CF5 | C2F6 Emissions | Total Equivalent CO2 Emissions |  | CF4 Slope Coefficient | C2F6/CF4 Weight Fraction
 |  |  | A1 | A2 | B | B1 | B2 = B/B1 | C1 | C | D = A x B x C | E1 | E | F = D x E | F = (D x 6.5)+(F x 9.2) |  | C2 | E2
 |  | Units |  | (t Al) | AEM
(min per cell ler day) | AEF 
(AE per cell per day) | AED
(min per AE) |  |  | (kg CF4) |  |  | (kg C2F6) | (t CO2)
 |  | Ex: VSS with default factors | Vertical Stud Søderberg | 1000 | 10 | 1 | 10 | 0.092 | 0.092 | 920 | 0.053 | 0.053 | 48.76 | 6428.59
 |  |  |  |  |  | 0.14 |  |  |  | 0.018
 |  | Potline 1 Period 1 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 0.143 | 0.121 |  |  |  |  |  |  |  | Centre Work Prebake
 |  | Potline 1 Period 2 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 0.272 | 0.252 |  |  |  |  |  |  |  | Side Work Prebake
 |  | Potline 1 Period 3 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 0.092 | 0.053 |  |  |  |  |  |  |  | Vertical Stud Søderberg
 |  | Potline 1 Period 4 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 0.099 | 0.085 |  |  |  |  |  |  |  | Horizontal Stud Søderberg
 |  | Potline 2 Period 1 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 2 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 3 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 4 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 1 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 2 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 3 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 4 |  |  |  |  | 0 |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  |  |  | 0 |  |  |  |  |  | 0 | Total of Column G = |  | 0 | 0
 |  |  |  |  |  |  |  |  |  | All t in metric tonnes
 | Equation 2 - Anode Effect Overvoltage (AEO) Method (Prebake potlines with Pechiney control system only)
 |  |  | A |  | B |  |  | C |  | D | E |  | F | G |  | Tier 2 Factors
 |  |  | Type of cell | Weight of aluminium produced | Anode Effect Parameters |  |  | Tier 3 site specific CF4 Overvoltage Coefficients | Used CF4 Overvoltage Coefficients | CF4 Emissions | Tier 3 site specific Weight Fraction C2F6/CF4 | Used Weight Fraction C2F6/CF5 | C2F6 Emissions | Total Equivalent CO2 Emissions |  | CF4 Overvoltage Coefficient | C2F6/CF4 Weight Fraction
 |  |  | A1 | A2 | B1 | B2 | B3 | C1 | C | D = (A2 x B2 x C) / B3 | E1 | E | F = D x E | F =(D x 6.5)+(F x 9.2) |  | C2 | E2
 |  | Units |  | (t Al) | AEF 
(AE per cell per day) | AEO (mV per cell) | Current efficiency (%) |  |  | (kg CF4) |  |  | (kg C2F6) | (t CO2)
 |  | Ex: CWPB with default factors | Centre Work Prebake | 1000 | 0.1 | 5 | 0.95 | 1.16 | 1.16 | 61.0526 | 0.121 | 0.121 | 7.38737 | 464.806 |  | CF4 Overvoltage Coefficient | C2F6/CF4 Weight Fraction
 |  | Potline 1 Period 1 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 1.16 | 0.121 |  |  |  |  |  |  |  | CWPB Algebraic AEO
 |  | Potline 1 Period 2 |  |  |  | ] |  |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  | 3.65 | 0.252 |  |  |  |  |  |  |  | CWPB Positive AEO
 |  | Potline 1 Period 3 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  |  |  |  |  |  |  |  |  |  | SWPB Algebraic AEO
 |  | Potline 1 Period 4 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0 |  |  |  |  |  |  |  |  |  |  | SWPB Positive AEO
 |  | Potline 2 Period 1 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 2 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 3 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 2 Period 4 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 1 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 2 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 3 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  | Potline 3 Period 4 |  |  |  |  |  |  | 0.0 | 0 |  | 0.0 | 0 | 0
 |  |  |  | 0 |  |  |  |  |  | 0 | Total of Column G = |  | 0 | 0
 |  | All t in metric tonnes
