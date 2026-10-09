import AppKit
import Foundation
import PDFKit
import Vision

struct PageText: Codable {
    let page: Int
    let text: String
}

struct OCRResult: Codable {
    let pages: [PageText]
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data((message + "\n").utf8))
    exit(2)
}

guard CommandLine.arguments.count == 2 else { fail("invalid arguments") }
let url = URL(fileURLWithPath: CommandLine.arguments[1]).standardizedFileURL
guard let pdf = PDFDocument(url: url), pdf.pageCount > 0, pdf.pageCount <= 500 else {
    fail("invalid or unsupported PDF")
}

var output: [PageText] = []
for index in 0..<pdf.pageCount {
    guard let page = pdf.page(at: index) else {
        output.append(PageText(page: index + 1, text: ""))
        continue
    }
    let bounds = page.bounds(for: .mediaBox)
    let scale: CGFloat = 2.2
    let width = max(1, bounds.width * scale)
    let height = max(1, bounds.height * scale)
    guard width <= 6000, height <= 6000, width * height <= 20_000_000 else {
        output.append(PageText(page: index + 1, text: ""))
        continue
    }
    let size = CGSize(width: width, height: height)
    let image = page.thumbnail(of: size, for: .mediaBox)
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        output.append(PageText(page: index + 1, text: ""))
        continue
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["pt-BR"]
    request.usesLanguageCorrection = true
    do {
        try VNImageRequestHandler(cgImage: cgImage).perform([request])
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        output.append(PageText(page: index + 1, text: lines.joined(separator: "\n")))
    } catch {
        output.append(PageText(page: index + 1, text: ""))
    }
}

do {
    let data = try JSONEncoder().encode(OCRResult(pages: output))
    FileHandle.standardOutput.write(data)
} catch {
    fail("failed to encode OCR output")
}
